"""全自動モードの実行エンジン（スロット消化・CTA返信・初速バズ検知・トークン更新）"""

import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

import threads_api
from generator import Draft, Generator
from scheduling import BUZZ_WINDOW_HOURS, daily_slots, is_buzz, next_allowed_time, views_velocity
from store import Store, iso, parse, utcnow

log = logging.getLogger("threads-auto")

MISSED_SLOT_GRACE = timedelta(hours=3)  # これ以上遅れたスロットは諦める
BUZZ_CHECK_INTERVAL = timedelta(minutes=30)
TOKEN_REFRESH_AFTER = timedelta(days=30)  # 長期トークンは60日有効


class Engine:
    def __init__(self, store: Store, generator: Generator, client_factory):
        self.store = store
        self.generator = generator
        self.client_factory = client_factory  # () -> ThreadsClient | DryRunClient
        self._last_buzz_check: Optional[datetime] = None
        self._lock = threading.Lock()
        self.last_error: Optional[str] = None

    # --- 1回分の処理 ------------------------------------------------------
    def tick(self, now: Optional[datetime] = None) -> None:
        now = now or utcnow()
        with self._lock:
            s = self.store.load_settings()
            self._refresh_token_if_needed(now)
            if s.enabled:
                self._plan_slots(s, now)
                self._run_due_slots(s, now)
            self._send_due_ctas(s, now)
            if s.buzz_detection and (self._last_buzz_check is None
                                     or now - self._last_buzz_check >= BUZZ_CHECK_INTERVAL):
                self._last_buzz_check = now
                self._check_buzz(now)

    def _plan_slots(self, s, now: datetime) -> None:
        today = now.astimezone(ZoneInfo(s.timezone)).date()
        key = today.isoformat()
        if self.store.slots_for_day(key):
            return
        for idx, due in enumerate(daily_slots(s, today)):
            self.store.ensure_slot(key, idx, due)

    def _run_due_slots(self, s, now: datetime) -> None:
        for slot in self.store.pending_slots(now):
            if now - parse(slot["due_at"]) > MISSED_SLOT_GRACE:
                self.store.set_slot_status(slot["day"], slot["idx"], "skipped")
                continue
            allowed = next_allowed_time(s, now, self.store.post_times_since(now - timedelta(hours=24)),
                                        self.store.last_post_time())
            if allowed > now:
                log.info("上限・間隔のため %s まで待機", allowed.isoformat())
                return  # エラーにせず、次の tick で再判定
            try:
                self.publish(self._make_draft(s, now), s, now)
                self.store.set_slot_status(slot["day"], slot["idx"], "done")
                self.last_error = None
            except Exception as e:  # noqa: BLE001 - 失敗はスロットに記録して継続
                log.exception("自動投稿に失敗")
                self.last_error = str(e)
                self.store.set_slot_status(slot["day"], slot["idx"], "failed")
            return  # 1 tick で投稿するのは1件まで（最低間隔を守るため）

    def _make_draft(self, s, now: datetime) -> Draft:
        if s.recycle_buzz:
            row = self.store.recyclable_buzz_post(now - timedelta(days=s.recycle_min_age_days))
            if row:
                draft = self.generator.paraphrase(json.loads(row["parts_json"]), s)
                draft.recycled_from = row["id"]
                return draft
        return self.generator.generate(s, self.store.recent_texts())

    # --- 投稿 -------------------------------------------------------------
    def publish(self, draft: Draft, s, now: Optional[datetime] = None) -> int:
        now = now or utcnow()
        client = self.client_factory()
        ids = client.publish_chain(draft.parts, topic_tag=draft.topic_tag)
        cta_due = now + timedelta(minutes=s.cta_delay_minutes) if s.cta_text else None
        return self.store.add_post(
            threads_id=ids[0], parts=draft.parts, topic_tag=draft.topic_tag, score=draft.score,
            published_at=now, cta_due_at=cta_due, last_reply_id=ids[-1],
            recycled_from=draft.recycled_from)

    def _send_due_ctas(self, s, now: datetime) -> None:
        for row in self.store.due_ctas(now):
            if s.cta_text:
                try:
                    # 連投がある場合は最後の返信の後に CTA をつなげる
                    self.client_factory().publish_text(s.cta_text, reply_to_id=row["last_reply_id"])
                except Exception as e:  # noqa: BLE001
                    log.exception("CTA 返信に失敗")
                    self.last_error = str(e)
            self.store.mark_cta_done(row["id"])

    # --- 初速バズ検知 -----------------------------------------------------
    def _check_buzz(self, now: datetime) -> None:
        lo, hi = BUZZ_WINDOW_HOURS
        client = self.client_factory()
        for row in self.store.posts_published_between(now - timedelta(hours=hi), now - timedelta(hours=lo)):
            try:
                metrics = client.insights(row["threads_id"])
            except Exception:  # noqa: BLE001
                log.exception("インサイト取得に失敗")
                continue
            v = views_velocity(metrics.get("views"), parse(row["published_at"]), now)
            if v is None:
                continue
            buzz = is_buzz(v, self.store.baseline_velocities(row["id"]))
            self.store.update_metrics(row["id"], metrics, v, buzz)

    # --- トークン ---------------------------------------------------------
    def _refresh_token_if_needed(self, now: datetime) -> None:
        token, obtained = self.store.get_kv("access_token"), self.store.get_kv("token_obtained_at")
        if not token or not obtained or now - parse(obtained) < TOKEN_REFRESH_AFTER:
            return
        try:
            data = threads_api.refresh_token(token)
            self.store.set_kv("access_token", data["access_token"])
            self.store.set_kv("token_obtained_at", iso(now))
        except Exception as e:  # noqa: BLE001
            log.exception("トークン更新に失敗")
            self.last_error = str(e)

    # --- バックグラウンド実行 ---------------------------------------------
    def run_forever(self, stop: threading.Event, interval_seconds: float = 30) -> None:
        while not stop.is_set():
            try:
                self.tick()
            except Exception:  # noqa: BLE001
                log.exception("tick で例外")
            stop.wait(interval_seconds)

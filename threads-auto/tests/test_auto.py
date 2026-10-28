import json
import random
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine import Engine  # noqa: E402
from generator import Generator  # noqa: E402
from scheduling import daily_slots, is_buzz, next_allowed_time  # noqa: E402
from settings import AutoSettings  # noqa: E402
from store import Store  # noqa: E402
from threads_api import DryRunClient  # noqa: E402

T0 = datetime(2026, 10, 28, 3, 0, tzinfo=timezone.utc)  # 12:00 JST


class FakeMessages:
    """Claude の応答を順番に返すフェイク"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        text = json.dumps(self.replies.pop(0), ensure_ascii=False)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)])


def fake_generator(replies):
    msgs = FakeMessages(replies)
    return Generator(SimpleNamespace(beta=SimpleNamespace(messages=msgs))), msgs


# --- scheduling ------------------------------------------------------------

def test_daily_slots_within_jitter():
    s = AutoSettings(posts_per_day=2, times=["09:00", "12:30", "19:00"], jitter_minutes=15)
    slots = daily_slots(s, date(2026, 10, 28), random.Random(1))
    assert len(slots) == 2
    noon = slots[1]
    assert (noon.hour, noon.minute) >= (12, 15) and (noon.hour, noon.minute) <= (12, 45)


def test_min_interval_and_daily_cap():
    s = AutoSettings(max_posts_24h=3, min_interval_minutes=20)
    last = T0 - timedelta(minutes=5)
    assert next_allowed_time(s, T0, [last], last) == last + timedelta(minutes=20)
    posts = [T0 - timedelta(hours=h) for h in (10, 5, 2)]
    assert next_allowed_time(s, T0, posts, posts[-1]) == posts[0] + timedelta(hours=24)


def test_buzz_needs_history_and_double_speed():
    assert not is_buzz(100, [10, 10, 10, 10])
    assert is_buzz(21, [10, 10, 10, 10, 10])
    assert not is_buzz(19, [10, 10, 10, 10, 10])


# --- generator -------------------------------------------------------------

def test_quality_gate_retries_then_uses_best():
    s = AutoSettings(quality_gate=True, quality_threshold=90, quality_max_retries=2)
    gen, msgs = fake_generator([
        {"parts": ["A"], "topic_tag": ""}, {"score": 50, "reason": ""},
        {"parts": ["B"], "topic_tag": ""}, {"score": 80, "reason": ""},
        {"parts": ["C"], "topic_tag": ""}, {"score": 60, "reason": ""},
    ])
    d = gen.generate(s, [])
    assert d.parts == ["B"] and d.score == 80
    assert len(msgs.calls) == 6
    assert msgs.calls[0]["output_config"]["format"]["type"] == "json_schema"


def test_thread_parts_trimmed_and_tag_sanitized():
    s = AutoSettings(thread_mode=True, max_thread_parts=2, topic_tag_mode="ai")
    gen, _ = fake_generator([{"parts": ["1", "2", "3"], "topic_tag": "#副業.Tips&"}])
    d = gen.generate(s, [])
    assert d.parts == ["1", "2"]
    assert d.topic_tag == "副業Tips"


# --- engine ----------------------------------------------------------------

def make_engine(tmp_path, settings, replies):
    store = Store(str(tmp_path / "t.db"))
    store.save_settings(settings)
    gen, _ = fake_generator(replies)
    client = DryRunClient()
    return Engine(store, gen, lambda: client), store, client


def test_engine_posts_thread_then_cta_reply(tmp_path):
    s = AutoSettings(enabled=True, posts_per_day=1, times=["11:50"], jitter_minutes=0,
                     thread_mode=True, cta_text="詳しくはプロフィールへ", cta_delay_minutes=3,
                     buzz_detection=False)
    engine, store, client = make_engine(tmp_path, s, [{"parts": ["本文", "続き"], "topic_tag": ""}])
    engine.tick(T0)
    assert [p["text"] for p in client.published] == ["本文", "続き"]
    assert client.published[1]["reply_to_id"] == client.published[0]["id"]
    engine.tick(T0 + timedelta(minutes=1))
    assert len(client.published) == 2  # CTA はまだ
    engine.tick(T0 + timedelta(minutes=4))
    assert client.published[2]["text"] == "詳しくはプロフィールへ"
    assert client.published[2]["reply_to_id"] == client.published[1]["id"]
    assert store.slots_for_day("2026-10-28")[0]["status"] == "done"


def test_engine_waits_when_interval_not_met(tmp_path):
    s = AutoSettings(enabled=True, posts_per_day=2, times=["11:50", "11:55"], jitter_minutes=0,
                     min_interval_minutes=20, buzz_detection=False)
    engine, store, client = make_engine(tmp_path, s, [{"parts": ["1本目"], "topic_tag": ""},
                                                      {"parts": ["2本目"], "topic_tag": ""}])
    engine.tick(T0)
    engine.tick(T0 + timedelta(minutes=5))
    assert len(client.published) == 1  # 待機中（失敗にはしない）
    assert store.slots_for_day("2026-10-28")[1]["status"] == "pending"
    engine.tick(T0 + timedelta(minutes=21))
    assert [p["text"] for p in client.published] == ["1本目", "2本目"]


def test_disabled_does_nothing(tmp_path):
    engine, _, client = make_engine(tmp_path, AutoSettings(enabled=False), [])
    engine.tick(T0)
    assert client.published == []


def test_invalid_settings_rejected():
    with pytest.raises(ValueError):
        AutoSettings(times=["25:00"])
    with pytest.raises(ValueError):
        AutoSettings(fixed_topic_tag="a.b")

"""SQLite による設定・投稿履歴・スロットの保存"""

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import List, Optional

from settings import AutoSettings

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS posts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    threads_id TEXT,
    text TEXT NOT NULL,
    parts_json TEXT NOT NULL,
    topic_tag TEXT,
    score INTEGER,
    published_at TEXT NOT NULL,
    cta_due_at TEXT,
    cta_done INTEGER NOT NULL DEFAULT 0,
    last_reply_id TEXT,
    views INTEGER,
    likes INTEGER,
    replies INTEGER,
    reposts INTEGER,
    velocity REAL,
    buzz INTEGER NOT NULL DEFAULT 0,
    recycled_from INTEGER,
    recycled INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS slots (
    day TEXT NOT NULL,
    idx INTEGER NOT NULL,
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    PRIMARY KEY (day, idx)
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


class Store:
    def __init__(self, path: str = "threads_auto.db"):
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)

    def _exec(self, sql: str, args=()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, args)
            self._conn.commit()
            return cur

    # --- key/value -------------------------------------------------------
    def get_kv(self, key: str) -> Optional[str]:
        row = self._exec("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_kv(self, key: str, value: str) -> None:
        self._exec("INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

    def load_settings(self) -> AutoSettings:
        raw = self.get_kv("settings")
        return AutoSettings.model_validate_json(raw) if raw else AutoSettings()

    def save_settings(self, s: AutoSettings) -> None:
        self.set_kv("settings", s.model_dump_json())

    # --- posts -----------------------------------------------------------
    def add_post(self, *, threads_id: Optional[str], parts: List[str], topic_tag: Optional[str],
                 score: Optional[int], published_at: datetime, cta_due_at: Optional[datetime],
                 last_reply_id: Optional[str], recycled_from: Optional[int] = None) -> int:
        cur = self._exec(
            "INSERT INTO posts(threads_id, text, parts_json, topic_tag, score, published_at, cta_due_at,"
            " last_reply_id, recycled_from) VALUES(?,?,?,?,?,?,?,?,?)",
            (threads_id, parts[0], json.dumps(parts, ensure_ascii=False), topic_tag, score,
             iso(published_at), iso(cta_due_at) if cta_due_at else None, last_reply_id, recycled_from),
        )
        if recycled_from:
            self._exec("UPDATE posts SET recycled=1 WHERE id=?", (recycled_from,))
        return cur.lastrowid

    def post_times_since(self, since: datetime) -> List[datetime]:
        rows = self._exec("SELECT published_at FROM posts WHERE published_at >= ? ORDER BY published_at",
                          (iso(since),)).fetchall()
        return [parse(r["published_at"]) for r in rows]

    def last_post_time(self) -> Optional[datetime]:
        row = self._exec("SELECT MAX(published_at) AS t FROM posts").fetchone()
        return parse(row["t"]) if row and row["t"] else None

    def recent_texts(self, limit: int = 20) -> List[str]:
        rows = self._exec("SELECT text FROM posts ORDER BY published_at DESC LIMIT ?", (limit,)).fetchall()
        return [r["text"] for r in rows]

    def list_posts(self, limit: int = 50) -> List[dict]:
        rows = self._exec("SELECT * FROM posts ORDER BY published_at DESC LIMIT ?", (limit,)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["parts"] = json.loads(d.pop("parts_json"))
            out.append(d)
        return out

    def due_ctas(self, now: datetime) -> List[sqlite3.Row]:
        return self._exec(
            "SELECT * FROM posts WHERE cta_due_at IS NOT NULL AND cta_done=0 AND cta_due_at <= ?",
            (iso(now),)).fetchall()

    def mark_cta_done(self, post_id: int) -> None:
        self._exec("UPDATE posts SET cta_done=1 WHERE id=?", (post_id,))

    def posts_published_between(self, start: datetime, end: datetime) -> List[sqlite3.Row]:
        return self._exec(
            "SELECT * FROM posts WHERE threads_id IS NOT NULL AND published_at >= ? AND published_at <= ?",
            (iso(start), iso(end))).fetchall()

    def update_metrics(self, post_id: int, metrics: dict, velocity: float, buzz: bool) -> None:
        self._exec(
            "UPDATE posts SET views=?, likes=?, replies=?, reposts=?, velocity=?, buzz=MAX(buzz, ?) WHERE id=?",
            (metrics.get("views"), metrics.get("likes"), metrics.get("replies"), metrics.get("reposts"),
             velocity, int(buzz), post_id))

    def baseline_velocities(self, exclude_id: int) -> List[float]:
        rows = self._exec("SELECT velocity FROM posts WHERE velocity IS NOT NULL AND id != ?",
                          (exclude_id,)).fetchall()
        return [r["velocity"] for r in rows]

    def recyclable_buzz_post(self, older_than: datetime) -> Optional[sqlite3.Row]:
        return self._exec(
            "SELECT * FROM posts WHERE buzz=1 AND recycled=0 AND recycled_from IS NULL AND published_at <= ?"
            " ORDER BY velocity DESC LIMIT 1", (iso(older_than),)).fetchone()

    # --- slots -----------------------------------------------------------
    def ensure_slot(self, day: str, idx: int, due_at: datetime) -> None:
        self._exec("INSERT OR IGNORE INTO slots(day, idx, due_at) VALUES(?,?,?)", (day, idx, iso(due_at)))

    def pending_slots(self, now: datetime) -> List[sqlite3.Row]:
        return self._exec("SELECT * FROM slots WHERE status='pending' AND due_at <= ? ORDER BY due_at",
                          (iso(now),)).fetchall()

    def set_slot_status(self, day: str, idx: int, status: str) -> None:
        self._exec("UPDATE slots SET status=? WHERE day=? AND idx=?", (status, day, idx))

    def clear_pending_slots(self, from_day: str) -> None:
        self._exec("DELETE FROM slots WHERE status='pending' AND day >= ?", (from_day,))

    def slots_for_day(self, day: str) -> List[dict]:
        return [dict(r) for r in self._exec("SELECT * FROM slots WHERE day=? ORDER BY idx", (day,)).fetchall()]

"""投稿スロットの計算（時刻＋ゆらぎ）と、アカウント保護のためのペース制御"""

import random
import statistics
from datetime import date, datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from settings import AutoSettings


def daily_slots(s: AutoSettings, day: date, rng: random.Random = random) -> List[datetime]:
    """例: 12:30 + ゆらぎ15分 → 12:15〜12:45 のどこか"""
    tz = ZoneInfo(s.timezone)
    out = []
    for t in s.times[:s.posts_per_day]:
        hh, mm = map(int, t.split(":"))
        base = datetime(day.year, day.month, day.day, hh, mm, tzinfo=tz)
        offset = rng.uniform(-s.jitter_minutes, s.jitter_minutes) if s.jitter_minutes else 0
        out.append(base + timedelta(minutes=offset))
    return sorted(out)


def next_allowed_time(s: AutoSettings, now: datetime, recent_posts: List[datetime],
                      last_post: Optional[datetime]) -> datetime:
    """直近24時間の投稿数上限と最低投稿間隔を守れる最も早い時刻。上限なら待機する"""
    candidates = [now]
    if last_post:
        candidates.append(last_post + timedelta(minutes=s.min_interval_minutes))
    window = sorted(t for t in recent_posts if t > now - timedelta(hours=24))
    if len(window) >= s.max_posts_24h:
        # 窓から押し出す必要がある最古の投稿が24時間を過ぎる時刻
        candidates.append(window[len(window) - s.max_posts_24h] + timedelta(hours=24))
    return max(candidates)


BUZZ_MIN_HISTORY = 5
BUZZ_FACTOR = 2.0
BUZZ_WINDOW_HOURS = (1, 6)


def views_velocity(views: Optional[int], published_at: datetime, now: datetime) -> Optional[float]:
    hours = (now - published_at).total_seconds() / 3600
    if views is None or hours <= 0:
        return None
    return views / hours


def is_buzz(velocity: float, history: List[float]) -> bool:
    """普段（過去投稿の中央値）の2倍以上の速さで伸びていれば初速バズ。履歴5件未満は判定しない"""
    if len(history) < BUZZ_MIN_HISTORY:
        return False
    base = statistics.median(history)
    return base > 0 and velocity >= BUZZ_FACTOR * base

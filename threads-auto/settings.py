"""全自動モードの設定項目"""

import re
from typing import List, Literal

from pydantic import BaseModel, Field, field_validator


class AutoSettings(BaseModel):
    enabled: bool = False

    # 投稿スケジュール
    posts_per_day: int = Field(1, ge=1, le=3)
    times: List[str] = ["09:00", "12:30", "19:00"]
    jitter_minutes: int = Field(15, ge=0, le=60)
    timezone: str = "Asia/Tokyo"

    # 投稿内容
    tone: Literal["casual", "business", "humor", "inspiration"] = "casual"
    theme: str = ""
    extra_instructions: str = ""
    example_posts: str = ""  # お手本サンプル

    # スレッド形式（連投）
    thread_mode: bool = False
    max_thread_parts: int = Field(3, ge=2, le=5)

    # CTA セルフリプライ（返信枠を使う）
    cta_text: str = Field("", max_length=500)
    cta_delay_minutes: int = Field(3, ge=1, le=60)

    # トピックタグ
    topic_tag_mode: Literal["none", "fixed", "ai"] = "none"
    fixed_topic_tag: str = ""

    # 品質ゲート
    quality_gate: bool = False
    quality_threshold: int = Field(70, ge=0, le=100)
    quality_max_retries: int = Field(2, ge=0, le=5)

    # 初速バズ検知・リサイクル
    buzz_detection: bool = True
    recycle_buzz: bool = False
    recycle_min_age_days: int = Field(7, ge=1)

    # アカウント保護
    max_posts_24h: int = Field(25, ge=1, le=250)
    min_interval_minutes: int = Field(20, ge=1)

    # AI
    model: str = "claude-opus-5-5"

    @field_validator("times")
    @classmethod
    def _check_times(cls, v: List[str]) -> List[str]:
        for t in v:
            if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
                raise ValueError(f"時刻は HH:MM 形式で指定してください: {t}")
        return v

    @field_validator("fixed_topic_tag")
    @classmethod
    def _check_tag(cls, v: str) -> str:
        # Threads API: 1〜50文字、ピリオドとアンパサンドは不可
        if v and (len(v) > 50 or "." in v or "&" in v):
            raise ValueError("トピックタグは50文字以内で、'.' と '&' は使えません")
        return v

"""Claude による投稿生成・品質ゲート採点・リサイクル用の言い換え"""

import json
from dataclasses import dataclass
from typing import List, Optional

import anthropic

from settings import AutoSettings

MAX_CHARS = 500  # Threads のテキスト投稿上限

TONES = {
    "casual": "親しみやすいカジュアルな口調",
    "business": "信頼感のあるビジネス寄りの口調",
    "humor": "クスッと笑えるユーモアのある口調",
    "inspiration": "前向きな気持ちになれるインスピレーション系の口調",
}

POST_SCHEMA = {
    "type": "object",
    "properties": {
        "parts": {"type": "array", "items": {"type": "string"},
                  "description": "1要素目が本投稿、2要素目以降は連投（返信）"},
        "topic_tag": {"type": "string", "description": "投稿の話題タグ（#なし）。不要なら空文字"},
    },
    "required": ["parts", "topic_tag"],
    "additionalProperties": False,
}

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "description": "0〜100のバズりやすさ"},
        "reason": {"type": "string"},
    },
    "required": ["score", "reason"],
    "additionalProperties": False,
}

SYSTEM = (
    "あなたは Threads（Meta のSNS）の運用担当です。読者の役に立ち、最後まで読みたくなる日本語の投稿を書きます。"
    "1投稿は必ず500文字以内。冒頭1行目で興味を引くフックを置き、ハッシュタグの羅列やリンクは本文に入れません。"
    "誇大表現・断定的な効果の約束・他人の権利を侵害する内容は書きません。"
)


class GenerationError(RuntimeError):
    pass


@dataclass
class Draft:
    parts: List[str]
    topic_tag: Optional[str]
    score: Optional[int] = None
    recycled_from: Optional[int] = None


class Generator:
    def __init__(self, client: Optional[anthropic.Anthropic] = None):
        self._client = client

    @property
    def client(self) -> anthropic.Anthropic:
        # API キー未設定でもサーバー自体は起動できるよう、初回利用時に生成する
        if self._client is None:
            self._client = anthropic.Anthropic()
        return self._client

    def _call(self, model: str, prompt: str, schema: dict) -> dict:
        response = self.client.beta.messages.create(
            model=model,
            max_tokens=16000,
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": schema}},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if response.stop_reason == "refusal":
            raise GenerationError("AI が生成を辞退しました（refusal）")
        if response.stop_reason == "max_tokens":
            raise GenerationError("出力が max_tokens で打ち切られました")
        text = "".join(b.text for b in response.content if b.type == "text")
        return json.loads(text)

    def _post_prompt(self, s: AutoSettings, recent: List[str]) -> str:
        lines = [
            f"テーマ・トピック: {s.theme or '（指定なし。役に立つ日常の知見）'}",
            f"トーン: {TONES[s.tone]}",
        ]
        if s.thread_mode:
            lines.append(f"スレッド形式で 2〜{s.max_thread_parts} 本の連投にしてください。"
                         "1本目は結論とフック、2本目以降で具体例や手順を書きます。")
        else:
            lines.append("1本だけの投稿にしてください（parts は1要素）。")
        if s.topic_tag_mode == "ai":
            lines.append("投稿内容に合う話題タグを1つ topic_tag に入れてください（50文字以内、'.' と '&' は不可）。")
        else:
            lines.append("topic_tag は空文字にしてください。")
        if s.extra_instructions:
            lines.append(f"追加指示: {s.extra_instructions}")
        if s.example_posts:
            lines.append("次のお手本の構成・語り口を参考にしてください（内容はコピーしない）:\n"
                         f"<example>\n{s.example_posts}\n</example>")
        if recent:
            joined = "\n---\n".join(t[:200] for t in recent)
            lines.append(f"最近の投稿と内容・書き出しが重複しないようにしてください:\n<recent>\n{joined}\n</recent>")
        return "\n\n".join(lines)

    def _normalize(self, data: dict, s: AutoSettings) -> Draft:
        parts = [p.strip() for p in data.get("parts", []) if p and p.strip()]
        if not parts:
            raise GenerationError("投稿本文が空でした")
        limit = s.max_thread_parts if s.thread_mode else 1
        parts = [p[:MAX_CHARS] for p in parts[:limit]]
        if s.topic_tag_mode == "fixed":
            tag = s.fixed_topic_tag or None
        elif s.topic_tag_mode == "ai":
            tag = (data.get("topic_tag") or "").lstrip("#").replace(".", "").replace("&", "")[:50] or None
        else:
            tag = None
        return Draft(parts=parts, topic_tag=tag)

    def score(self, draft: Draft, s: AutoSettings) -> int:
        body = "\n---\n".join(draft.parts)
        prompt = ("次の Threads 投稿が伸びるか（冒頭のフック、具体性、読みやすさ、共感・保存されやすさ）を"
                  f"0〜100で採点してください。\n<post>\n{body}\n</post>")
        data = self._call(s.model, prompt, SCORE_SCHEMA)
        return max(0, min(100, int(data["score"])))

    def generate(self, s: AutoSettings, recent: List[str]) -> Draft:
        """品質ゲート ON の場合、合格点に届かなければ作り直し、全滅なら最高得点を使う"""
        prompt = self._post_prompt(s, recent)
        attempts = 1 + (s.quality_max_retries if s.quality_gate else 0)
        best: Optional[Draft] = None
        for _ in range(attempts):
            draft = self._normalize(self._call(s.model, prompt, POST_SCHEMA), s)
            if not s.quality_gate:
                return draft
            draft.score = self.score(draft, s)
            if best is None or draft.score > best.score:
                best = draft
            if draft.score >= s.quality_threshold:
                return draft
        return best

    def paraphrase(self, parts: List[str], s: AutoSettings) -> Draft:
        body = "\n---\n".join(parts)
        prompt = ("次の過去に伸びた投稿を、構成と要点は保ったまま言い回しと具体例を変えて書き直してください。"
                  f"連投の本数は元と同じにしてください。\n<post>\n{body}\n</post>\n\n"
                  "topic_tag は空文字にしてください。")
        data = self._call(s.model, prompt, POST_SCHEMA)
        data["parts"] = data.get("parts", [])[:len(parts)]
        recycle_settings = s.model_copy(update={"thread_mode": len(parts) > 1, "max_thread_parts": max(2, len(parts))})
        return self._normalize(data, recycle_settings)

from pathlib import Path
import os

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from script_builder import (
    ScriptRequest,
    build_outline,
    build_prompt,
    build_template,
    options_payload,
    target_chars,
)

load_dotenv()

BASE_DIR = Path(__file__).parent
MODEL = os.getenv("CLAUDE_MODEL", "claude-opus-5-5")

app = FastAPI(title="YouTube台本メーカー")
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


def ai_enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


@app.get("/")
def index():
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/api/options")
def options():
    return {**options_payload(), "ai_enabled": ai_enabled()}


@app.post("/api/build")
def build(req: ScriptRequest):
    """構成表・台本テンプレート・AI用プロンプトを返す（AI不要）"""
    outline = build_outline(req)
    blocked = req.mode == "client" and not req.ai_allowed
    return {
        "target_chars": target_chars(req),
        "outline": outline,
        "template": build_template(req, outline),
        "prompt": None if blocked else build_prompt(req, outline),
    }


@app.post("/api/generate")
def generate(req: ScriptRequest):
    """Claude API で台本の下書きを生成する"""
    if req.mode == "client" and not req.ai_allowed:
        raise HTTPException(403, "この依頼はAI利用が許可されていないため、生成できません")
    if not ai_enabled():
        raise HTTPException(503, "ANTHROPIC_API_KEY が設定されていません")

    prompt = build_prompt(req, build_outline(req))
    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=16000,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.RateLimitError:
        raise HTTPException(429, "混み合っています。少し待ってから再度お試しください")
    except anthropic.APIStatusError as e:
        raise HTTPException(502, f"AI生成に失敗しました（{e.status_code}）")
    except anthropic.APIConnectionError:
        raise HTTPException(502, "AIに接続できませんでした")

    if response.stop_reason == "refusal":
        raise HTTPException(422, "この内容ではAI生成できませんでした。テーマを見直してください")

    script = "".join(b.text for b in response.content if b.type == "text").strip()
    return {"script": script, "truncated": response.stop_reason == "max_tokens"}

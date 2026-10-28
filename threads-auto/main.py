"""Threads 全自動モード - FastAPI サーバー

起動: uvicorn main:app --port 8000
"""

import logging
import os
import secrets
import threading
from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import threads_api
from engine import Engine
from generator import Draft, GenerationError, Generator
from settings import AutoSettings
from store import Store, iso, utcnow

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ID = os.getenv("THREADS_APP_ID", "")
APP_SECRET = os.getenv("THREADS_APP_SECRET", "")
REDIRECT_URI = os.getenv("THREADS_REDIRECT_URI", "http://localhost:8000/oauth/callback")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"

store = Store(os.getenv("DB_PATH", os.path.join(BASE_DIR, "threads_auto.db")))
_dry_client = threads_api.DryRunClient()


def client_factory():
    token, user_id = store.get_kv("access_token"), store.get_kv("user_id")
    if DRY_RUN or not token or not user_id:
        return _dry_client
    return threads_api.ThreadsClient(user_id, token)


generator = Generator()
engine = Engine(store, generator, client_factory)
_stop = threading.Event()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker = threading.Thread(target=engine.run_forever, args=(_stop,), daemon=True)
    worker.start()
    yield
    _stop.set()


app = FastAPI(title="Threads 全自動モード", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


@app.get("/")
def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.get("/api/settings")
def get_settings() -> AutoSettings:
    return store.load_settings()


@app.put("/api/settings")
def put_settings(s: AutoSettings) -> AutoSettings:
    store.save_settings(s)
    # 時刻や頻度の変更を今日の未消化スロットに反映させる
    store.clear_pending_slots(utcnow().astimezone(ZoneInfo(s.timezone)).date().isoformat())
    return s


@app.post("/api/preview")
def preview(s: AutoSettings) -> dict:
    """保存前に、生成される投稿の雰囲気を確認する（投稿はしない）"""
    try:
        d = generator.generate(s, store.recent_texts())
    except GenerationError as e:
        raise HTTPException(422, str(e))
    return {"parts": d.parts, "topic_tag": d.topic_tag, "score": d.score}


@app.post("/api/post-now")
def post_now(d: dict) -> dict:
    """プレビュー結果などをそのまま投稿する（ペース制御の対象外の手動投稿）"""
    s = store.load_settings()
    parts = [p for p in d.get("parts", []) if p.strip()]
    if not parts:
        raise HTTPException(400, "parts が空です")
    post_id = engine.publish(Draft(parts=parts, topic_tag=d.get("topic_tag") or None), s)
    return {"id": post_id}


@app.get("/api/status")
def status() -> dict:
    s = store.load_settings()
    today = utcnow().astimezone(ZoneInfo(s.timezone)).date().isoformat()
    connected = bool(store.get_kv("access_token") and store.get_kv("user_id"))
    limit = {}
    if connected and not DRY_RUN:
        try:
            limit = client_factory().publishing_limit()
        except Exception as e:  # noqa: BLE001
            limit = {"error": str(e)}
    return {"enabled": s.enabled, "dry_run": DRY_RUN or not connected, "connected": connected,
            "today_slots": store.slots_for_day(today), "last_error": engine.last_error,
            "publishing_limit": limit}


@app.get("/api/posts")
def posts(limit: int = 50) -> list:
    return store.list_posts(limit)


@app.get("/oauth/login")
def oauth_login():
    if not APP_ID:
        raise HTTPException(400, "THREADS_APP_ID が未設定です（.env を確認）")
    state = secrets.token_urlsafe(16)
    store.set_kv("oauth_state", state)
    return RedirectResponse(threads_api.authorize_url(APP_ID, REDIRECT_URI, state))


@app.get("/oauth/callback")
def oauth_callback(code: str, state: str = ""):
    if not state or state != store.get_kv("oauth_state"):
        raise HTTPException(400, "state が一致しません")
    data = threads_api.exchange_code(APP_ID, APP_SECRET, REDIRECT_URI, code.split("#")[0])
    store.set_kv("access_token", data["access_token"])
    store.set_kv("user_id", data["user_id"])
    store.set_kv("token_obtained_at", iso(utcnow()))
    return RedirectResponse("/")

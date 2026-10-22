"""自動投稿ツール：予約した日時に X / Threads / ブログへ投稿する。

起動: python3 app.py  →  http://127.0.0.1:8000
"""
import json
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
DATA_FILE = BASE_DIR / "data" / "posts.json"
CHECK_INTERVAL = 20  # 秒ごとに予約をチェック


def load_env(path=BASE_DIR / ".env"):
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env()

import platforms  # noqa: E402  (.env 読み込み後に import)

lock = threading.Lock()


# ---------- 保存 ----------

def load_posts():
    if not DATA_FILE.exists():
        return []
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_posts(posts):
    DATA_FILE.parent.mkdir(exist_ok=True)
    tmp = DATA_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(DATA_FILE)


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def parse_time(s):
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.astimezone()  # タイムゾーン無しはサーバーのローカル時刻とみなす
    return dt


# ---------- 予約実行 ----------

def run_due_posts():
    now = datetime.now(timezone.utc)
    with lock:
        posts = load_posts()
        due = [p for p in posts if p["status"] == "scheduled" and parse_time(p["scheduled_at"]) <= now]
        for p in due:
            p["status"] = "posting"
        if due:
            save_posts(posts)

    for p in due:
        results = {}
        for pf in p["platforms"]:
            try:
                results[pf] = {"ok": True, "info": platforms.send(pf, p)}
            except Exception as e:  # 1つ失敗しても他の投稿先は続ける
                results[pf] = {"ok": False, "info": str(e)}
        oks = [r["ok"] for r in results.values()]
        status = "done" if all(oks) else ("partial" if any(oks) else "failed")
        print(f"[{now_iso()}] {p['id'][:8]} → {status} {results}", flush=True)

        with lock:
            posts = load_posts()
            for q in posts:
                if q["id"] == p["id"]:
                    q.update(status=status, results=results, posted_at=now_iso())
            save_posts(posts)


def scheduler_loop():
    with lock:  # 前回の実行中に止まった投稿は再予約に戻す
        posts = load_posts()
        for p in posts:
            if p["status"] == "posting":
                p["status"] = "scheduled"
        save_posts(posts)
    while True:
        try:
            run_due_posts()
        except Exception as e:
            print(f"scheduler error: {e}", flush=True)
        time.sleep(CHECK_INTERVAL)


# ---------- API ----------

def validate(body):
    content = (body.get("content") or "").strip()
    targets = [p for p in body.get("platforms", []) if p in platforms.PLATFORMS]
    times = body.get("scheduled_at") or []
    if isinstance(times, str):
        times = [times]
    if not content:
        raise ValueError("投稿内容を入力してください")
    if not targets:
        raise ValueError("投稿先を1つ以上選んでください")
    if not times:
        raise ValueError("日付を1つ以上選んでください")
    for t in times:
        parse_time(t)
    if "x" in targets and platforms.x_length(content) > platforms.X_LIMIT:
        raise ValueError("X の文字数上限（全角140字 / 半角280字）を超えています")
    if "threads" in targets and len(content) > platforms.THREADS_LIMIT:
        raise ValueError("Threads の文字数上限（500字）を超えています")
    return content, (body.get("title") or "").strip(), targets, times


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def send_json(self, data, code=200):
        raw = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def read_body(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        if self.path == "/api/status":
            return self.send_json({
                "dry_run": platforms.dry_run(),
                "platforms": {k: {"name": v, "configured": platforms.is_configured(k)}
                              for k, v in platforms.PLATFORMS.items()},
            })
        if self.path == "/api/posts":
            with lock:
                return self.send_json(load_posts())
        if self.path in ("/", "/index.html"):
            raw = (STATIC_DIR / "index.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            return self.wfile.write(raw)
        self.send_json({"error": "not found"}, 404)

    def do_POST(self):
        parts = self.path.strip("/").split("/")
        try:
            body = self.read_body()
        except json.JSONDecodeError:
            return self.send_json({"error": "JSON が不正です"}, 400)

        if parts == ["api", "posts"]:
            try:
                content, title, targets, times = validate(body)
            except ValueError as e:
                return self.send_json({"error": str(e)}, 400)
            created = [{
                "id": uuid.uuid4().hex,
                "content": content,
                "title": title,
                "platforms": targets,
                "scheduled_at": parse_time(t).isoformat(),
                "status": "scheduled",
                "results": {},
                "created_at": now_iso(),
            } for t in times]
            with lock:
                save_posts(load_posts() + created)
            return self.send_json(created, 201)

        # /api/posts/<id>/cancel  /api/posts/<id>/now
        if len(parts) == 4 and parts[:2] == ["api", "posts"] and parts[3] in ("cancel", "now"):
            with lock:
                posts = load_posts()
                post = next((p for p in posts if p["id"] == parts[2]), None)
                if not post:
                    return self.send_json({"error": "予約が見つかりません"}, 404)
                if post["status"] != "scheduled":
                    return self.send_json({"error": "予約中の投稿のみ操作できます"}, 409)
                if parts[3] == "cancel":
                    post["status"] = "canceled"
                else:
                    post["scheduled_at"] = now_iso()
                save_posts(posts)
            if parts[3] == "now":
                threading.Thread(target=run_due_posts, daemon=True).start()
            return self.send_json(post)

        self.send_json({"error": "not found"}, 404)

    def do_DELETE(self):
        parts = self.path.strip("/").split("/")
        if len(parts) == 3 and parts[:2] == ["api", "posts"]:
            with lock:
                posts = load_posts()
                target = next((p for p in posts if p["id"] == parts[2]), None)
                if not target:
                    return self.send_json({"error": "予約が見つかりません"}, 404)
                if target["status"] in ("scheduled", "posting"):
                    return self.send_json({"error": "予約中の投稿は先に取消してください"}, 409)
                save_posts([p for p in posts if p["id"] != parts[2]])
            return self.send_json({"ok": True})
        self.send_json({"error": "not found"}, 404)


def main():
    host = os.environ.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT", "8000"))
    threading.Thread(target=scheduler_loop, daemon=True).start()
    mode = "テストモード（DRY_RUN）" if platforms.dry_run() else "本番モード"
    print(f"自動投稿ツール起動: http://{host}:{port}  [{mode}]", flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    main()

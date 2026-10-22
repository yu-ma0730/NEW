"""投稿先アカウントの連携（ログイン）と、トークンの保存・自動更新。

- X       : OAuth 2.0（PKCE）で「X でログイン」→ アクセストークンを自動更新
- Threads : Meta の OAuth でログイン、またはアクセストークンを貼り付け → 長期トークン（60日）に交換・自動更新
- ブログ  : WordPress のサイト URL・ユーザー名・アプリケーションパスワードで接続

連携情報は data/accounts.json に保存する（このファイルは秘密情報なので共有しないこと）。
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from pathlib import Path

from platforms import PostError, _request

ACCOUNTS_FILE = Path(__file__).resolve().parent / "data" / "accounts.json"
X_SCOPES = "tweet.read tweet.write users.read offline.access"
THREADS_SCOPES = "threads_basic,threads_content_publish"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}

_lock = threading.RLock()
_pending = {}  # state → {"platform", "verifier", "redirect", "created"}


# ---------- 保存 ----------

def load():
    with _lock:
        if not ACCOUNTS_FILE.exists():
            return {}
        return json.loads(ACCOUNTS_FILE.read_text(encoding="utf-8"))


def save(data):
    with _lock:
        ACCOUNTS_FILE.parent.mkdir(exist_ok=True)
        tmp = ACCOUNTS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(tmp, 0o600)
        tmp.replace(ACCOUNTS_FILE)


def get(platform):
    return load().get(platform, {})


def update(platform, **fields):
    with _lock:
        data = load()
        data.setdefault(platform, {}).update(fields)
        save(data)
        return data[platform]


def disconnect(platform):
    """ログイン状態だけ消す（アプリ設定の Client ID などは残す）。"""
    keep = {"x": ("client_id", "client_secret"), "threads": ("app_id", "app_secret"), "blog": ()}[platform]
    with _lock:
        data = load()
        data[platform] = {k: v for k, v in data.get(platform, {}).items() if k in keep}
        save(data)


def connected(platform):
    acc = get(platform)
    if platform == "blog":
        return bool(acc.get("app_password"))
    return bool(acc.get("access_token"))


def public_info():
    """画面表示用。トークンやパスワードは返さない。"""
    data = load()
    info = {}
    for pf in ("x", "threads", "blog"):
        acc = data.get(pf, {})
        info[pf] = {
            "connected": connected(pf),
            "username": acc.get("username", ""),
            "expires_at": acc.get("expires_at"),
            "app_ready": bool(acc.get("client_id") if pf == "x" else acc.get("app_id") and acc.get("app_secret")),
            "client_id": acc.get("client_id") or acc.get("app_id") or "",
            "url": acc.get("url", ""),
            "user": acc.get("user", ""),
        }
    return info


def _start(platform, redirect, verifier=None):
    now = time.time()
    for s in [s for s, v in _pending.items() if now - v["created"] > 600]:
        del _pending[s]
    state = secrets.token_urlsafe(24)
    _pending[state] = {"platform": platform, "verifier": verifier, "redirect": redirect, "created": now}
    return state


def _finish(platform, state):
    pending = _pending.pop(state or "", None)
    if not pending or pending["platform"] != platform:
        raise PostError("ログインの有効期限が切れたか、不正なリクエストです。もう一度やり直してください")
    return pending


# ---------- X ----------

def x_save_app(client_id, client_secret=""):
    if not client_id:
        raise PostError("Client ID を入力してください")
    update("x", client_id=client_id.strip(), client_secret=client_secret.strip())


def x_login_url(redirect):
    acc = get("x")
    if not acc.get("client_id"):
        raise PostError("先に X の Client ID を保存してください")
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = _start("x", redirect, verifier)
    return "https://x.com/i/oauth2/authorize?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": acc["client_id"], "redirect_uri": redirect,
        "scope": X_SCOPES, "state": state, "code_challenge": challenge, "code_challenge_method": "S256",
    })


def _x_token_request(params):
    acc = get("x")
    headers = dict(FORM)
    params = {**params, "client_id": acc["client_id"]}
    if acc.get("client_secret"):  # 機密クライアント（Web App）は Basic 認証が必要
        basic = base64.b64encode(f"{acc['client_id']}:{acc['client_secret']}".encode()).decode()
        headers["Authorization"] = f"Basic {basic}"
    data = _request("https://api.x.com/2/oauth2/token", headers=headers, body=urllib.parse.urlencode(params).encode())
    update("x", access_token=data["access_token"],
           refresh_token=data.get("refresh_token", acc.get("refresh_token", "")),
           expires_at=int(time.time()) + int(data.get("expires_in", 7200)))


def x_callback(code, state):
    pending = _finish("x", state)
    _x_token_request({"grant_type": "authorization_code", "code": code,
                      "redirect_uri": pending["redirect"], "code_verifier": pending["verifier"]})
    me = _request("https://api.x.com/2/users/me", method="GET",
                  headers={"Authorization": f"Bearer {get('x')['access_token']}"})
    update("x", username="@" + me.get("data", {}).get("username", ""))


def x_access_token():
    """有効なアクセストークンを返す（期限が近ければ refresh_token で更新）。"""
    with _lock:
        acc = get("x")
        if acc.get("expires_at", 0) - time.time() < 120:
            if not acc.get("refresh_token"):
                raise PostError("X のログイン期限が切れました。アカウント連携からログインし直してください")
            _x_token_request({"grant_type": "refresh_token", "refresh_token": acc["refresh_token"]})
        return get("x")["access_token"]


# ---------- Threads ----------

def threads_save_app(app_id, app_secret):
    if not app_id or not app_secret:
        raise PostError("App ID と App Secret を入力してください")
    update("threads", app_id=app_id.strip(), app_secret=app_secret.strip())


def threads_login_url(redirect):
    acc = get("threads")
    if not (acc.get("app_id") and acc.get("app_secret")):
        raise PostError("先に Threads の App ID / App Secret を保存してください")
    state = _start("threads", redirect)
    return "https://threads.net/oauth/authorize?" + urllib.parse.urlencode({
        "client_id": acc["app_id"], "redirect_uri": redirect, "scope": THREADS_SCOPES,
        "response_type": "code", "state": state,
    })


def threads_callback(code, state):
    pending = _finish("threads", state)
    acc = get("threads")
    short = _request("https://graph.threads.net/oauth/access_token", headers=FORM, body=urllib.parse.urlencode({
        "client_id": acc["app_id"], "client_secret": acc["app_secret"], "grant_type": "authorization_code",
        "redirect_uri": pending["redirect"], "code": code,
    }).encode())
    threads_set_token(short["access_token"])


def threads_set_token(token):
    """短期トークンなら長期（60日）に交換し、ユーザー名を確認して保存する。"""
    token = (token or "").strip()
    if not token:
        raise PostError("アクセストークンを入力してください")
    acc = get("threads")
    expires_at = None
    if acc.get("app_secret"):
        try:
            long = _request("https://graph.threads.net/access_token?" + urllib.parse.urlencode({
                "grant_type": "th_exchange_token", "client_secret": acc["app_secret"], "access_token": token,
            }), method="GET")
            token = long["access_token"]
            expires_at = int(time.time()) + int(long.get("expires_in", 5184000))
        except PostError:
            pass  # すでに長期トークンの場合などは交換できないのでそのまま使う
    me = _request("https://graph.threads.net/v1.0/me?" + urllib.parse.urlencode(
        {"fields": "id,username", "access_token": token}), method="GET")
    update("threads", access_token=token, username="@" + me.get("username", ""),
           expires_at=expires_at or int(time.time()) + 5184000)


def threads_access_token():
    """有効なトークンを返す（残り7日を切ったら自動更新）。"""
    with _lock:
        acc = get("threads")
        if acc.get("expires_at", 0) - time.time() < 7 * 86400:
            try:
                data = _request("https://graph.threads.net/refresh_access_token?" + urllib.parse.urlencode({
                    "grant_type": "th_refresh_token", "access_token": acc["access_token"],
                }), method="GET")
                update("threads", access_token=data["access_token"],
                       expires_at=int(time.time()) + int(data.get("expires_in", 5184000)))
            except PostError:
                if acc.get("expires_at", 0) < time.time():
                    raise PostError("Threads のログイン期限が切れました。アカウント連携からログインし直してください")
        return get("threads")["access_token"]


# ---------- ブログ（WordPress） ----------

def blog_connect(url, user, app_password):
    url, user, app_password = (url or "").strip().rstrip("/"), (user or "").strip(), (app_password or "").strip()
    if not (url and user and app_password):
        raise PostError("サイト URL・ユーザー名・アプリケーションパスワードをすべて入力してください")
    if not url.startswith(("https://", "http://")):
        url = "https://" + url
    basic = base64.b64encode(f"{user}:{app_password}".encode()).decode()
    me = _request(url + "/wp-json/wp/v2/users/me", method="GET", headers={"Authorization": f"Basic {basic}"})
    update("blog", url=url, user=user, app_password=app_password, username=me.get("name", user))

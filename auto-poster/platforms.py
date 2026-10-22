"""各投稿先（X / Threads / ブログ）への投稿処理。

標準ライブラリのみで動くようにしている。認証情報は環境変数（.env）から読む。
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

PLATFORMS = {
    "x": "X",
    "threads": "Threads",
    "blog": "ブログ",
}

# 文字数上限（X は全角を 2 として数える）
X_LIMIT = 280
THREADS_LIMIT = 500


class PostError(Exception):
    pass


def env(name):
    return os.environ.get(name, "").strip()


def is_configured(platform):
    if platform == "x":
        return all(env(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"))
    if platform == "threads":
        return bool(env("THREADS_ACCESS_TOKEN"))
    if platform == "blog":
        return all(env(k) for k in ("WP_URL", "WP_USER", "WP_APP_PASSWORD"))
    return False


def dry_run():
    return env("DRY_RUN") in ("1", "true", "yes")


def x_length(text):
    """X の重み付き文字数（ASCII 等は 1、日本語など全角は 2）の近似値。"""
    n = 0
    for ch in text:
        cp = ord(ch)
        if cp <= 0x10FF or 0x2000 <= cp <= 0x200D or 0x2010 <= cp <= 0x201F or 0x2032 <= cp <= 0x2037:
            n += 1
        else:
            n += 2
    return n


def _request(url, method="POST", headers=None, body=None):
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        raise PostError(f"HTTP {e.code}: {detail}") from None
    except urllib.error.URLError as e:
        raise PostError(f"接続エラー: {e.reason}") from None
    return json.loads(raw) if raw else {}


# ---------- X (旧 Twitter) : API v2 + OAuth 1.0a ----------

def _pct(s):
    return urllib.parse.quote(str(s), safe="~-._")


def _oauth1_header(method, url):
    params = {
        "oauth_consumer_key": env("X_API_KEY"),
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": str(int(time.time())),
        "oauth_token": env("X_ACCESS_TOKEN"),
        "oauth_version": "1.0",
    }
    # JSON ボディは署名対象に含めない
    param_str = "&".join(f"{_pct(k)}={_pct(v)}" for k, v in sorted(params.items()))
    base = "&".join([method.upper(), _pct(url), _pct(param_str)])
    key = f"{_pct(env('X_API_SECRET'))}&{_pct(env('X_ACCESS_SECRET'))}"
    sig = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    params["oauth_signature"] = sig
    return "OAuth " + ", ".join(f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(params.items()))


def post_x(post):
    text = post["content"]
    if x_length(text) > X_LIMIT:
        raise PostError(f"X の文字数上限（{X_LIMIT}、全角は2換算）を超えています")
    url = "https://api.x.com/2/tweets"
    data = _request(
        url,
        headers={"Authorization": _oauth1_header("POST", url), "Content-Type": "application/json"},
        body=json.dumps({"text": text}).encode(),
    )
    tweet_id = data.get("data", {}).get("id")
    return f"https://x.com/i/web/status/{tweet_id}" if tweet_id else ""


# ---------- Threads : Graph API（コンテナ作成 → 公開の2段階） ----------

def post_threads(post):
    text = post["content"]
    if len(text) > THREADS_LIMIT:
        raise PostError(f"Threads の文字数上限（{THREADS_LIMIT}）を超えています")
    base = "https://graph.threads.net/v1.0/me"
    token = env("THREADS_ACCESS_TOKEN")
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    container = _request(
        f"{base}/threads",
        headers=form,
        body=urllib.parse.urlencode({"media_type": "TEXT", "text": text, "access_token": token}).encode(),
    )
    creation_id = container.get("id")
    if not creation_id:
        raise PostError(f"コンテナ作成に失敗: {container}")
    published = _request(
        f"{base}/threads_publish",
        headers=form,
        body=urllib.parse.urlencode({"creation_id": creation_id, "access_token": token}).encode(),
    )
    return f"Threads 投稿ID: {published.get('id', '')}"


# ---------- ブログ : WordPress REST API（アプリケーションパスワード） ----------

def post_blog(post):
    title = post.get("title") or post["content"].splitlines()[0][:60]
    content = "".join(f"<p>{line}</p>" for line in _escape(post["content"]).splitlines() if line.strip())
    auth = base64.b64encode(f"{env('WP_USER')}:{env('WP_APP_PASSWORD')}".encode()).decode()
    data = _request(
        env("WP_URL").rstrip("/") + "/wp-json/wp/v2/posts",
        headers={"Authorization": f"Basic {auth}", "Content-Type": "application/json"},
        body=json.dumps({"title": title, "content": content, "status": "publish"}).encode(),
    )
    return data.get("link", "")


def _escape(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


SENDERS = {"x": post_x, "threads": post_threads, "blog": post_blog}


def send(platform, post):
    """投稿して結果 URL などを返す。失敗時は PostError。"""
    if dry_run():
        return "（テストモード：実際には投稿していません）"
    if not is_configured(platform):
        raise PostError(f"{PLATFORMS[platform]} の認証情報が .env に設定されていません")
    return SENDERS[platform](post)

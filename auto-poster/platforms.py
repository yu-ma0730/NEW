"""各投稿先（X / Threads / ブログ）への投稿処理。

標準ライブラリのみで動くようにしている。認証情報は「アカウント連携」画面で
ログインしたもの（accounts.py）を優先し、なければ環境変数（.env）を使う。
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

ALL_PLATFORMS = {
    "x": "X",
    "threads": "Threads",
    "blog": "ブログ",
}

# 使う投稿先（.env の ENABLED_PLATFORMS、カンマ区切り）。今は Threads だけ。
_enabled = [p.strip() for p in os.environ.get("ENABLED_PLATFORMS", "threads").split(",")]
PLATFORMS = {k: v for k, v in ALL_PLATFORMS.items() if k in _enabled} or {"threads": "Threads"}

# 文字数上限（X は全角を 2 として数える）
X_LIMIT = 280
THREADS_LIMIT = 500
TOPIC_LIMIT = 50


class PostError(Exception):
    pass


def env(name):
    return os.environ.get(name, "").strip()


def is_configured(platform):
    import accounts  # 循環 import を避けるためここで読む
    return accounts.connected(platform) or env_configured(platform)


def env_configured(platform):
    if platform == "x":
        return all(env(k) for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"))
    if platform == "threads":
        return bool(env("THREADS_ACCESS_TOKEN"))
    if platform == "blog":
        return all(env(k) for k in ("WP_URL", "WP_USER", "WP_APP_PASSWORD"))
    return False


def dry_run():
    return env("DRY_RUN") in ("1", "true", "yes")


def parts_of(post, platform):
    """スレッド（連投）の各投稿テキスト。旧形式（content のみ）の予約にも対応。"""
    body = post.get("bodies", {}).get(platform)
    if body and body.get("parts"):
        return body["parts"]
    return [post["content"]]


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
    texts = parts_of(post, "x")
    if any(x_length(t) > X_LIMIT for t in texts):
        raise PostError(f"X の文字数上限（{X_LIMIT}、全角は2換算）を超えています")
    import accounts
    url = "https://api.x.com/2/tweets"
    if accounts.connected("x"):
        auth = lambda: f"Bearer {accounts.x_access_token()}"  # noqa: E731
    else:
        auth = lambda: _oauth1_header("POST", url)  # noqa: E731
    first_id = prev_id = None
    for text in texts:  # 2件目以降は前のポストへの返信としてつなげる
        payload = {"text": text}
        if prev_id:
            payload["reply"] = {"in_reply_to_tweet_id": prev_id}
        data = _request(
            url,
            headers={"Authorization": auth(), "Content-Type": "application/json"},
            body=json.dumps(payload).encode(),
        )
        prev_id = data.get("data", {}).get("id")
        first_id = first_id or prev_id
    return f"https://x.com/i/web/status/{first_id}" if first_id else ""


# ---------- Threads : Graph API（コンテナ作成 → 公開の2段階） ----------

def post_threads(post):
    texts = parts_of(post, "threads")
    if any(len(t) > THREADS_LIMIT for t in texts):
        raise PostError(f"Threads の文字数上限（{THREADS_LIMIT}）を超えています")
    topic = post.get("bodies", {}).get("threads", {}).get("topic", "")
    base = "https://graph.threads.net/v1.0/me"
    import accounts
    token = accounts.threads_access_token() if accounts.connected("threads") else env("THREADS_ACCESS_TOKEN")
    form = {"Content-Type": "application/x-www-form-urlencoded"}
    first_id = prev_id = None
    for text in texts:  # 2件目以降は前の投稿への返信（スレッドに追加）としてつなげる
        params = {"media_type": "TEXT", "text": text, "access_token": token}
        if prev_id:
            params["reply_to_id"] = prev_id
        elif topic:
            params["topic_tag"] = topic
        container = _request(f"{base}/threads", headers=form, body=urllib.parse.urlencode(params).encode())
        creation_id = container.get("id")
        if not creation_id:
            raise PostError(f"コンテナ作成に失敗: {container}")
        published = _request(
            f"{base}/threads_publish",
            headers=form,
            body=urllib.parse.urlencode({"creation_id": creation_id, "access_token": token}).encode(),
        )
        prev_id = published.get("id")
        first_id = first_id or prev_id
    return f"Threads 投稿ID: {first_id or ''}（{len(texts)}件）"


# ---------- ブログ : WordPress REST API（アプリケーションパスワード） ----------

def post_blog(post):
    blog = post.get("bodies", {}).get("blog") or {"title": post.get("title", ""), "body": post["content"]}
    text = blog["body"]
    title = blog.get("title") or text.splitlines()[0][:60]
    content = "".join(f"<p>{line}</p>" for line in _escape(text).splitlines() if line.strip())
    import accounts
    acc = accounts.get("blog") if accounts.connected("blog") else {
        "url": env("WP_URL"), "user": env("WP_USER"), "app_password": env("WP_APP_PASSWORD")}
    auth = base64.b64encode(f"{acc['user']}:{acc['app_password']}".encode()).decode()
    data = _request(
        acc["url"].rstrip("/") + "/wp-json/wp/v2/posts",
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
        raise PostError(f"{ALL_PLATFORMS[platform]} のアカウントが連携されていません（画面の「アカウント連携」からログイン）")
    return SENDERS[platform](post)

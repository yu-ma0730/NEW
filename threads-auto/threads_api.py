"""Threads API（Meta 公式）クライアント

参照: https://developers.facebook.com/docs/threads/posts
      https://developers.facebook.com/docs/threads/reference/publishing
      https://developers.facebook.com/docs/threads/troubleshooting
      https://developers.facebook.com/docs/threads/get-started/get-access-tokens-and-permissions
      https://developers.facebook.com/docs/threads/get-started/long-lived-tokens
      https://developers.facebook.com/docs/threads/insights
"""

import time
from typing import List, Optional
from urllib.parse import urlencode

import requests

GRAPH = "https://graph.threads.com"
VERSION = "v1.0"
SCOPES = "threads_basic,threads_content_publish,threads_manage_replies,threads_manage_insights"


class ThreadsError(RuntimeError):
    pass


def authorize_url(app_id: str, redirect_uri: str, state: str) -> str:
    q = urlencode({"client_id": app_id, "redirect_uri": redirect_uri, "scope": SCOPES,
                   "response_type": "code", "state": state})
    return f"https://threads.com/oauth/authorize?{q}"


def _check(res: requests.Response) -> dict:
    try:
        data = res.json()
    except ValueError:
        raise ThreadsError(f"HTTP {res.status_code}: {res.text[:300]}")
    if res.status_code >= 400 or "error" in data:
        raise ThreadsError(f"HTTP {res.status_code}: {data.get('error', data)}")
    return data


def exchange_code(app_id: str, app_secret: str, redirect_uri: str, code: str) -> dict:
    """認可コード → 短期トークン → 長期トークン（60日）。user_id を含めて返す"""
    short = _check(requests.post(f"{GRAPH}/oauth/access_token", data={
        "client_id": app_id, "client_secret": app_secret, "grant_type": "authorization_code",
        "redirect_uri": redirect_uri, "code": code}, timeout=30))
    long = _check(requests.get(f"{GRAPH}/access_token", params={
        "grant_type": "th_exchange_token", "client_secret": app_secret,
        "access_token": short["access_token"]}, timeout=30))
    return {"access_token": long["access_token"], "expires_in": long.get("expires_in"),
            "user_id": str(short["user_id"])}


def refresh_token(access_token: str) -> dict:
    return _check(requests.get(f"{GRAPH}/refresh_access_token", params={
        "grant_type": "th_refresh_token", "access_token": access_token}, timeout=30))


class ThreadsClient:
    def __init__(self, user_id: str, access_token: str, publish_wait_seconds: float = 30):
        self.user_id = user_id
        self.token = access_token
        # 公式ドキュメントはコンテナ作成から公開まで平均30秒待つことを推奨
        self.publish_wait_seconds = publish_wait_seconds

    def _post(self, path: str, data: dict) -> dict:
        data = {**data, "access_token": self.token}
        return _check(requests.post(f"{GRAPH}/{VERSION}/{path}", data=data, timeout=30))

    def _get(self, path: str, params: dict) -> dict:
        params = {**params, "access_token": self.token}
        return _check(requests.get(f"{GRAPH}/{VERSION}/{path}", params=params, timeout=30))

    def publish_text(self, text: str, reply_to_id: Optional[str] = None,
                     topic_tag: Optional[str] = None) -> str:
        body = {"media_type": "TEXT", "text": text}
        if reply_to_id:
            body["reply_to_id"] = reply_to_id
        if topic_tag:
            body["topic_tag"] = topic_tag
        container = self._post(f"{self.user_id}/threads", body)["id"]
        time.sleep(self.publish_wait_seconds)
        return self._post(f"{self.user_id}/threads_publish", {"creation_id": container})["id"]

    def publish_chain(self, parts: List[str], topic_tag: Optional[str] = None) -> List[str]:
        """1本目を投稿し、2本目以降は直前の投稿への返信としてつなげる（スレッド形式）"""
        ids = [self.publish_text(parts[0], topic_tag=topic_tag)]
        for part in parts[1:]:
            ids.append(self.publish_text(part, reply_to_id=ids[-1]))
        return ids

    def publishing_limit(self) -> dict:
        data = self._get(f"{self.user_id}/threads_publishing_limit",
                         {"fields": "quota_usage,config,reply_quota_usage,reply_config"})
        return data["data"][0] if data.get("data") else {}

    def insights(self, media_id: str) -> dict:
        data = self._get(f"{media_id}/insights", {"metric": "views,likes,replies,reposts"})
        out = {}
        for m in data.get("data", []):
            values = m.get("values") or [{}]
            out[m["name"]] = values[0].get("value", m.get("total_value", {}).get("value"))
        return out


class DryRunClient:
    """Threads 未連携でも動作確認できるよう、投稿をログに出すだけのクライアント"""

    def __init__(self):
        self._n = 0
        self.published: List[dict] = []

    def publish_text(self, text, reply_to_id=None, topic_tag=None) -> str:
        self._n += 1
        mid = f"dry-{int(time.time())}-{self._n}"
        self.published.append({"id": mid, "text": text, "reply_to_id": reply_to_id, "topic_tag": topic_tag})
        print(f"[DRY-RUN] publish {mid} reply_to={reply_to_id} tag={topic_tag}\n{text}\n")
        return mid

    def publish_chain(self, parts, topic_tag=None):
        ids = [self.publish_text(parts[0], topic_tag=topic_tag)]
        for part in parts[1:]:
            ids.append(self.publish_text(part, reply_to_id=ids[-1]))
        return ids

    def publishing_limit(self) -> dict:
        return {}

    def insights(self, media_id: str) -> dict:
        return {}

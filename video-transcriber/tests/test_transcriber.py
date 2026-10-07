"""ネットワーク不要の単体テスト。実行: cd video-transcriber && python -m pytest -q"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import transcriber

# UTAGE のページは、プレイヤー設定を JSON で埋め込み、URL の "/" を "\/" とエスケープしている
UTAGE_LIKE_HTML = r"""<html><head><title></title></head><body>
<script>var elements = [{"type":"video","video_type":"app",
"title":"自動化講座（第1話）",
"src":"https:\/\/cdn.example.com\/videos\/abc\/video.m3u8",
"thumbnail_url":"https:\/\/cdn.example.com\/videos\/abc\/thumbnail.jpg"}];</script>
</body></html>"""


class FakeResponse:
    def __init__(self, text, content_type="text/html; charset=utf-8"):
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"content-type": content_type}
        self.encoding = "utf-8"
        self.apparent_encoding = "utf-8"

    def raise_for_status(self):
        pass


@pytest.fixture
def fake_page(monkeypatch):
    def use(html):
        monkeypatch.setattr(transcriber.requests, "get", lambda *a, **k: FakeResponse(html))
    return use


def test_finds_json_escaped_video_url_and_its_title(fake_page):
    fake_page(UTAGE_LIKE_HTML)
    titles = {}
    urls = transcriber.find_media_in_html("https://utage.example/p/xyz", titles)
    assert urls == ["https://cdn.example.com/videos/abc/video.m3u8"]
    assert titles[urls[0]] == "自動化講座（第1話）"


def test_finds_video_tags_and_embeds(fake_page):
    fake_page("""<video src="/a.mp4"></video>
        <iframe src="https://player.vimeo.com/video/123"></iframe>
        <iframe src="https://ads.example.com/banner"></iframe>""")
    urls = transcriber.find_media_in_html("https://site.example/page")
    assert urls == ["https://site.example/a.mp4", "https://player.vimeo.com/video/123"]


def test_parse_vtt_strips_tags_and_repeated_lines():
    vtt = """WEBVTT

00:00:00.000 --> 00:00:02.000
こんにちは

00:00:01.500 --> 00:00:03.000 align:start
こんにちは
<c>今日は</c>晴れです
"""
    segs = transcriber.parse_vtt(vtt)
    assert [(s.start, s.text) for s in segs] == [(0.0, "こんにちは"), (1.5, "今日は晴れです")]


def test_render_formats():
    t = transcriber.Transcript("u", "title", "ja", "whisper",
                               [transcriber.Segment(0, 1.5, "一行目"), transcriber.Segment(61.25, 63, "二行目")])
    assert transcriber.render(t, "txt") == "一行目\n二行目"
    assert transcriber.render(t, "txt", timestamps=True).splitlines()[1] == "[00:01:01] 二行目"
    assert "00:01:01,250 --> 00:01:03,000" in transcriber.render(t, "srt")
    assert transcriber.render(t, "vtt").startswith("WEBVTT")

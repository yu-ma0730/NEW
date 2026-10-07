"""ページ内の動画を検出して文字起こしするコアモジュール。

処理の流れ:
1. ページ URL から動画を検出（yt-dlp → 失敗時は HTML を解析して <video> / iframe / 直リンクを探す）
2. 動画に字幕が付いていればそれを優先して使う（高速・無料）
3. 字幕が無ければ音声だけをダウンロードし、Whisper（faster-whisper）でローカル文字起こし
4. txt / srt / vtt / json で出力
"""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
import yt_dlp

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
VIDEO_EXT_RE = re.compile(r"\.(mp4|webm|m4v|mov|mkv|m3u8|mpd|mp3|m4a|wav|ogg)(\?|$)", re.I)
EMBED_HOST_RE = re.compile(
    r"(youtube\.com|youtu\.be|youtube-nocookie\.com|vimeo\.com|dailymotion\.com|"
    r"wistia\.(com|net)|loom\.com|streamable\.com|nicovideo\.jp|tiktok\.com)",
    re.I,
)

Log = Callable[[str], None]


@dataclass
class Segment:
    start: float
    end: float
    text: str


@dataclass
class Transcript:
    source_url: str
    title: str
    language: str | None
    method: str  # "subtitles" or "whisper"
    segments: list[Segment] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(s.text for s in self.segments)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["text"] = self.text
        return d


# ---------------------------------------------------------------------------
# 動画の検出
# ---------------------------------------------------------------------------

def _ydl_probe(url: str) -> list[dict]:
    """yt-dlp でページ内の動画情報を取得する（プレイリスト・埋め込みも展開）。"""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": False}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        return []
    if info.get("_type") in ("playlist", "multi_video"):
        return [e for e in (info.get("entries") or []) if e]
    return [info]


def find_media_in_html(page_url: str) -> list[str]:
    """HTML を解析して動画らしき URL を列挙する（yt-dlp が対応していないページ用）。"""
    resp = requests.get(page_url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    if "charset" not in resp.headers.get("content-type", "").lower():
        resp.encoding = resp.apparent_encoding  # 文字コード未指定のページ対策
    soup = BeautifulSoup(resp.text, "html.parser")
    found: list[str] = []

    def add(u: str | None) -> None:
        if not u or u.startswith(("data:", "blob:")):
            return
        full = urljoin(page_url, u.strip())
        if full not in found:
            found.append(full)

    for tag in soup.find_all(["video", "audio"]):
        add(tag.get("src"))
        for src in tag.find_all("source"):
            add(src.get("src"))
    for meta in soup.find_all("meta"):
        prop = (meta.get("property") or meta.get("name") or "").lower()
        if prop in ("og:video", "og:video:url", "og:video:secure_url", "twitter:player:stream"):
            add(meta.get("content"))
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src")
        if src and EMBED_HOST_RE.search(src):
            add(src)
    for a in soup.find_all("a", href=True):
        if VIDEO_EXT_RE.search(a["href"]):
            add(a["href"])
    # スクリプト内に直書きされた動画 URL
    for m in re.finditer(r"https?://[^\s\"'<>\\]+?\.(?:mp4|webm|m3u8)(?:\?[^\s\"'<>\\]*)?", resp.text):
        add(m.group(0))
    return found


def discover_videos(page_url: str, log: Log = print) -> list[dict]:
    """ページ内の動画を検出し、yt-dlp の info dict のリストを返す。"""
    try:
        entries = _ydl_probe(page_url)
        if entries:
            log(f"yt-dlp で {len(entries)} 件の動画を検出しました")
            return entries
    except yt_dlp.utils.DownloadError as e:
        log(f"yt-dlp で直接取得できませんでした。HTML を解析します ({str(e).splitlines()[0][:120]})")

    entries: list[dict] = []
    for media_url in find_media_in_html(page_url):
        try:
            entries.extend(_ydl_probe(media_url))
        except yt_dlp.utils.DownloadError:
            log(f"  取得できませんでした: {media_url}")
    log(f"HTML 解析で {len(entries)} 件の動画を検出しました")
    return entries


# ---------------------------------------------------------------------------
# 字幕の利用
# ---------------------------------------------------------------------------

def _ts_to_sec(ts: str) -> float:
    parts = ts.replace(",", ".").split(":")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + float(p)
    return sec


def parse_vtt(content: str) -> list[Segment]:
    """WebVTT を Segment に変換。自動字幕によくある重複行は除去する。"""
    segments: list[Segment] = []
    last_line = ""
    for block in re.split(r"\n\s*\n", content.replace("\r\n", "\n")):
        lines = block.strip().split("\n")
        idx = next((i for i, l in enumerate(lines) if "-->" in l), None)
        if idx is None:
            continue
        start_s, end_s = [t.strip().split(" ")[0] for t in lines[idx].split("-->")]
        new_lines = []
        for raw in lines[idx + 1:]:
            text = re.sub(r"<[^>]+>", "", raw).strip()
            if text and text != last_line:
                new_lines.append(text)
                last_line = text
        if new_lines:
            segments.append(Segment(_ts_to_sec(start_s), _ts_to_sec(end_s), " ".join(new_lines)))
    return segments


def _pick_subtitle(info: dict, langs: Iterable[str]) -> tuple[str, str, bool] | None:
    """(lang, vtt_url, is_auto) を返す。手動字幕 → 自動字幕の順で探す。"""
    for is_auto, key in ((False, "subtitles"), (True, "automatic_captions")):
        subs = info.get(key) or {}
        candidates = [l for l in langs if l in subs]
        # 指定言語が無ければ手動字幕は何語でも採用（自動字幕は翻訳版が大量にあるため元言語のみ）
        if not candidates and not is_auto:
            candidates = [l for l in subs if l != "live_chat"]
        if not candidates and is_auto:
            orig = info.get("language")
            candidates = [l for l in subs if orig and (l == orig or l.endswith("-orig"))]
        for lang in candidates:
            for fmt in subs[lang]:
                if fmt.get("ext") == "vtt" and fmt.get("url"):
                    return lang, fmt["url"], is_auto
    return None


def transcript_from_subtitles(info: dict, langs: Iterable[str], log: Log = print) -> Transcript | None:
    picked = _pick_subtitle(info, langs)
    if not picked:
        return None
    lang, url, is_auto = picked
    log(f"{'自動' if is_auto else '公式'}字幕（{lang}）を使用します")
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    segments = parse_vtt(resp.content.decode("utf-8-sig", errors="replace"))  # WebVTT は常に UTF-8
    if not segments:
        return None
    return Transcript(
        source_url=info.get("webpage_url") or info.get("url", ""),
        title=info.get("title", ""),
        language=lang,
        method="auto-subtitles" if is_auto else "subtitles",
        segments=segments,
    )


# ---------------------------------------------------------------------------
# Whisper による文字起こし
# ---------------------------------------------------------------------------

_model_cache: dict[tuple[str, str], object] = {}


def _load_model(model_size: str, device: str):
    from faster_whisper import WhisperModel  # 重いので必要時のみ import

    key = (model_size, device)
    if key not in _model_cache:
        compute_type = "int8" if device == "cpu" else "float16"
        try:
            _model_cache[key] = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as e:
            raise RuntimeError(
                f"Whisper モデル '{model_size}' を読み込めませんでした（初回は Hugging Face から"
                f"ダウンロードが必要です。ネットワーク接続を確認してください）: {e}"
            ) from e
    return _model_cache[key]


def download_audio(info: dict, workdir: Path, log: Log = print) -> Path:
    url = info.get("webpage_url") or info.get("url")
    opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "format": "bestaudio/best",
        "outtmpl": str(workdir / "audio.%(ext)s"),
        "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "m4a"}],
    }
    log("音声をダウンロードしています…")
    with yt_dlp.YoutubeDL(opts) as ydl:
        ydl.download([url])
    files = sorted(workdir.glob("audio.*"))
    if not files:
        raise RuntimeError("音声ファイルを取得できませんでした")
    return files[0]


def transcribe_file(
    audio_path: Path,
    model_size: str = "small",
    language: str | None = None,
    device: str = "cpu",
    log: Log = print,
) -> tuple[list[Segment], str | None]:
    log(f"Whisper（{model_size}）で文字起こし中…")
    model = _load_model(model_size, device)
    seg_iter, meta = model.transcribe(str(audio_path), language=language, vad_filter=True)
    segments = []
    for s in seg_iter:
        segments.append(Segment(round(s.start, 2), round(s.end, 2), s.text.strip()))
        log(f"  [{format_ts(s.start)}] {s.text.strip()}")
    return segments, meta.language


# ---------------------------------------------------------------------------
# まとめ
# ---------------------------------------------------------------------------

def transcribe_video(
    info: dict,
    language: str | None = None,
    model_size: str = "small",
    device: str = "cpu",
    use_subtitles: bool = True,
    log: Log = print,
) -> Transcript:
    title = info.get("title") or "untitled"
    log(f"▶ {title}")
    if use_subtitles:
        langs = [language] if language else ["ja", "en"]
        try:
            t = transcript_from_subtitles(info, langs, log)
            if t:
                return t
        except requests.RequestException as e:
            log(f"字幕の取得に失敗しました: {e}")
    with tempfile.TemporaryDirectory() as tmp:
        audio = download_audio(info, Path(tmp), log)
        segments, lang = transcribe_file(audio, model_size, language, device, log)
    return Transcript(
        source_url=info.get("webpage_url") or info.get("url", ""),
        title=title,
        language=lang,
        method="whisper",
        segments=segments,
    )


def transcribe_page(page_url: str, max_videos: int | None = None, log: Log = print, **kwargs) -> list[Transcript]:
    videos = discover_videos(page_url, log)
    if not videos:
        raise RuntimeError("ページ内に動画が見つかりませんでした")
    if max_videos:
        videos = videos[:max_videos]
    return [transcribe_video(v, log=log, **kwargs) for v in videos]


# ---------------------------------------------------------------------------
# 出力フォーマット
# ---------------------------------------------------------------------------

def format_ts(sec: float, sep: str = ".") -> str:
    ms = int(round(sec * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def to_srt(t: Transcript) -> str:
    return "\n".join(
        f"{i}\n{format_ts(s.start, ',')} --> {format_ts(s.end, ',')}\n{s.text}\n"
        for i, s in enumerate(t.segments, 1)
    )


def to_vtt(t: Transcript) -> str:
    body = "\n".join(f"{format_ts(s.start)} --> {format_ts(s.end)}\n{s.text}\n" for s in t.segments)
    return "WEBVTT\n\n" + body


def to_txt(t: Transcript, timestamps: bool = False) -> str:
    if timestamps:
        return "\n".join(f"[{format_ts(s.start)[:8]}] {s.text}" for s in t.segments)
    return t.text


def render(t: Transcript, fmt: str, timestamps: bool = False) -> str:
    if fmt == "srt":
        return to_srt(t)
    if fmt == "vtt":
        return to_vtt(t)
    if fmt == "json":
        return json.dumps(t.to_dict(), ensure_ascii=False, indent=2)
    return to_txt(t, timestamps)

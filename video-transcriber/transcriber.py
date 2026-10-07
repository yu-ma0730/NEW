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
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import requests
import yt_dlp
from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)
VIDEO_EXT_RE = re.compile(r"\.(mp4|webm|m4v|mov|mkv|m3u8|mpd|mp3|m4a|wav|ogg)(\?|$)", re.IGNORECASE)
EMBED_HOST_RE = re.compile(
    r"(youtube\.com|youtu\.be|youtube-nocookie\.com|vimeo\.com|dailymotion\.com|"
    r"wistia\.(com|net)|loom\.com|streamable\.com|nicovideo\.jp|tiktok\.com)",
    re.IGNORECASE,
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

def _http_headers(referer: str | None) -> dict:
    # 埋め込み動画（Vimeo の非公開埋め込みや独自 HLS 配信など）は Referer が無いと 403 になることが多い
    headers = {"User-Agent": USER_AGENT}
    if referer:
        headers["Referer"] = referer
    return headers


def _ydl_probe(url: str, referer: str | None = None) -> list[dict]:
    """yt-dlp でページ内の動画情報を取得する（プレイリスト・埋め込みも展開）。"""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": False,
        "http_headers": _http_headers(referer),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if info is None:
        return []
    entries = info.get("entries") if info.get("_type") in ("playlist", "multi_video") else [info]
    entries = [e for e in (entries or []) if e]
    for e in entries:
        e["_referer"] = referer
    return entries


def _json_title_near(raw: str, start: int, end: int) -> str | None:
    """URL を囲む JSON オブジェクト内の "title" を取り出す（UTAGE などのプレイヤー設定用）。"""
    obj_start = raw.rfind("{", 0, start)
    obj_end = raw.find("}", end)
    if obj_start < 0 or obj_end < 0:
        return None
    m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*)"', raw[obj_start:obj_end])
    if not m:
        return None
    try:
        title = json.loads(f'"{m.group(1)}"').strip()
    except json.JSONDecodeError:
        return None
    return title or None


def find_media_in_html(page_url: str, titles: dict[str, str] | None = None) -> list[str]:
    """HTML を解析して動画らしき URL を列挙する（yt-dlp が対応していないページ用）。

    titles を渡すと、JSON 設定内で見つかった動画の題名を {URL: 題名} で書き込む。
    """
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
    # スクリプト内に直書きされた動画 URL（JSON 内の "https:\/\/..." のようなエスケープも戻して探す）
    raw = resp.text.replace("\\/", "/")
    for m in re.finditer(r"https?://[^\s\"'<>\\]+?\.(?:mp4|webm|m3u8)(?:\?[^\s\"'<>\\]*)?", raw):
        add(m.group(0))
        title = _json_title_near(raw, m.start(), m.end())
        if titles is not None and title:
            titles.setdefault(m.group(0), title)
    return found


MEDIA_CT_RE = re.compile(r"^(video/|audio/)|mpegurl|dash\+xml", re.IGNORECASE)
PLAY_SELECTORS = [
    "video", ".vjs-big-play-button", ".plyr__control--overlaid", "[aria-label*=Play i]",
    "[class*=play-button]", "[class*=play_button]", "[class*=playBtn]", "button[class*=play]",
]


def _launch_browser(pw):
    """Chromium を起動。Playwright 同梱版が無ければ CHROMIUM_PATH / 既知パスを試す。"""
    try:
        return pw.chromium.launch()
    except Exception:
        import os
        for path in (os.environ.get("CHROMIUM_PATH"), "/opt/pw-browsers/chromium"):
            if path and Path(path).exists():
                return pw.chromium.launch(executable_path=path)
        raise


def find_media_with_browser(page_url: str, log: Log = print, wait_ms: int = 8000) -> list[str]:
    """ヘッドレスブラウザでページを実際に開き、JavaScript で読み込まれる動画を探す。

    UTAGE などの LP 作成ツールや独自プレイヤーは、HTML に動画 URL が書かれておらず
    再生ボタンを押した時点で .m3u8 / .mp4 を読み込むことが多いため、通信を監視して拾う。
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        log("Playwright が未インストールのためブラウザ解析をスキップします（pip install playwright）")
        return []

    found: list[str] = []

    def add(u: str | None) -> None:
        if u and not u.startswith(("data:", "blob:")) and u not in found:
            found.append(u)

    def on_response(resp) -> None:
        url = resp.url
        ct = resp.headers.get("content-type", "")
        # HLS/DASH の分割ファイル（.ts / .m4s）はマニフェストだけ拾えば十分
        if re.search(r"\.(ts|m4s|aac)(\?|$)", url, re.IGNORECASE):
            return
        if VIDEO_EXT_RE.search(url) or MEDIA_CT_RE.search(ct):
            add(url)

    with sync_playwright() as pw:
        browser = _launch_browser(pw)
        try:
            page = browser.new_page(user_agent=USER_AGENT)
            page.on("response", on_response)
            page.goto(page_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            # 遅延読み込み対策でページ下までスクロール
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(1000)
            # 再生ボタンを押して動画の読み込みを発生させる（メインページと iframe 内の両方）
            for frame in page.frames:
                for sel in PLAY_SELECTORS:
                    try:
                        for el in frame.query_selector_all(sel)[:5]:
                            el.click(timeout=1500, force=True)
                    except Exception:  # noqa: BLE001, S110 - 押せないボタンは無視して次を試す
                        pass
            page.wait_for_timeout(wait_ms)
            # 描画後の DOM から <video> と埋め込み iframe を回収
            for frame in page.frames:
                if EMBED_HOST_RE.search(frame.url):
                    add(frame.url)
                try:
                    srcs = frame.eval_on_selector_all(
                        "video, video source, audio, audio source",
                        "els => els.map(e => e.currentSrc || e.src).filter(Boolean)",
                    )
                    for src in srcs:
                        add(src)
                except Exception:  # noqa: BLE001, S110 - 閉じた iframe などは無視する
                    pass
        finally:
            browser.close()
    return found


def _probe_all(urls: list[str], referer: str, log: Log, titles: dict[str, str] | None = None) -> list[dict]:
    entries: list[dict] = []
    seen_ids: set[str] = set()
    for media_url in urls:
        try:
            for e in _ydl_probe(media_url, referer=referer):
                key = f"{e.get('extractor')}:{e.get('id')}"
                if key not in seen_ids:
                    seen_ids.add(key)
                    if titles and media_url in titles:
                        e["title"] = titles[media_url]
                        e["_titled"] = True
                    entries.append(e)
        except yt_dlp.utils.DownloadError:
            log(f"  取得できませんでした: {media_url[:150]}")
    return entries


def _page_title(page_url: str) -> str | None:
    try:
        resp = requests.get(page_url, headers={"User-Agent": USER_AGENT}, timeout=30)
        if "charset" not in resp.headers.get("content-type", "").lower():
            resp.encoding = resp.apparent_encoding
        soup = BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException:
        return None
    og = soup.find("meta", property="og:title")
    title = (og.get("content") if og else None) or (soup.title.string if soup.title else None)
    return title.strip() if title and title.strip() else None


def _label_with_page_title(entries: list[dict], page_url: str) -> list[dict]:
    """直リンク（.m3u8 等）から取った動画は題名が "video" などになるので、ページの題名を付ける。"""
    generic = [e for e in entries if e.get("extractor") == "generic" and not e.get("_titled")]
    if not generic:
        return entries
    title = _page_title(page_url)
    if title:
        for i, e in enumerate(generic, 1):
            e["title"] = title if len(generic) == 1 else f"{title} ({i})"
    return entries


def discover_videos(page_url: str, log: Log = print, use_browser: bool = True) -> list[dict]:
    """ページ内の動画を検出し、yt-dlp の info dict のリストを返す。

    1. yt-dlp に直接渡す  2. HTML を解析  3. ヘッドレスブラウザで実際に開く  の順に試す。
    """
    try:
        entries = _ydl_probe(page_url)
        if entries:
            log(f"yt-dlp で {len(entries)} 件の動画を検出しました")
            return entries
    except yt_dlp.utils.DownloadError as e:
        log(f"yt-dlp で直接取得できませんでした。HTML を解析します ({str(e).splitlines()[0][:120]})")

    try:
        titles: dict[str, str] = {}
        entries = _probe_all(find_media_in_html(page_url, titles), page_url, log, titles)
    except requests.RequestException as e:
        log(f"ページを取得できませんでした: {e}")
        entries = []
    if entries:
        log(f"HTML 解析で {len(entries)} 件の動画を検出しました")
        return _label_with_page_title(entries, page_url)

    if use_browser:
        log("HTML に動画が無いため、ブラウザでページを開いて探します…")
        try:
            urls = find_media_with_browser(page_url, log)
        except Exception as e:  # noqa: BLE001 - ブラウザ起動失敗やタイムアウトはログに出して続行
            log(f"ブラウザ解析に失敗しました: {str(e).splitlines()[0]}")
            urls = []
        entries = _probe_all(urls, page_url, log)
        log(f"ブラウザ解析で {len(entries)} 件の動画を検出しました")
    return _label_with_page_title(entries, page_url)


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
        "http_headers": _http_headers(info.get("_referer")),
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


def _decode_audio(path: Path, sr: int = 16000):
    """ffmpeg で 16kHz モノラルの波形に変換する。

    faster-whisper 内蔵のデコーダは PyAV のバージョン差で壊れることがある（PyAV 19 で
    open() の引数が削除された）ため、どの環境にもある ffmpeg で自前デコードする。
    """
    import subprocess

    import numpy as np

    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
           "-f", "f32le", "-ac", "1", "-ar", str(sr), "-"]
    out = subprocess.run(cmd, capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.float32)


def transcribe_file(
    audio_path: Path,
    model_size: str = "small",
    language: str | None = None,
    device: str = "cpu",
    log: Log = print,
) -> tuple[list[Segment], str | None]:
    log(f"Whisper（{model_size}）で文字起こし中…")
    model = _load_model(model_size, device)
    seg_iter, meta = model.transcribe(_decode_audio(audio_path), language=language, vad_filter=True)
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


def transcribe_page(
    page_url: str, max_videos: int | None = None, use_browser: bool = True, log: Log = print, **kwargs
) -> list[Transcript]:
    videos = discover_videos(page_url, log, use_browser=use_browser)
    if not videos:
        raise RuntimeError("ページ内に動画が見つかりませんでした")
    if max_videos:
        videos = videos[:max_videos]
    return [transcribe_video(v, log=log, **kwargs) for v in videos]


# ---------------------------------------------------------------------------
# 出力フォーマット
# ---------------------------------------------------------------------------

def format_ts(sec: float, sep: str = ".") -> str:
    ms = round(sec * 1000)
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

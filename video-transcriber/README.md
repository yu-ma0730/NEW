# 🎬 動画文字起こしツール（Video Transcriber）

Web ページの URL を渡すと、ページ内の動画を自動で見つけて文字起こしします。

## 仕組み

1. **動画の検出**: [yt-dlp](https://github.com/yt-dlp/yt-dlp)（YouTube・Vimeo・ニコニコ等 1000 以上のサイトに対応）でページを解析。
   対応外のページは HTML を解析し、`<video>` / `<source>` / `og:video` / 埋め込み iframe / スクリプト内の `.mp4`・`.m3u8` を探します。
2. **字幕があれば字幕を使用**（公式字幕 → 自動字幕の順）。速くて無料、精度も高めです。
3. **字幕が無ければ音声だけをダウンロード**し、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)（Whisper）でローカル PC 上で音声認識します。外部 API キーは不要です。
4. `txt` / `srt` / `vtt` / `json` で出力します。

## セットアップ

```bash
cd video-transcriber
pip install -r requirements.txt
# ffmpeg が必要です（macOS: brew install ffmpeg / Ubuntu: sudo apt install ffmpeg / Windows: winget install ffmpeg）
```

> Whisper モデルは初回実行時に Hugging Face から自動でダウンロードされます（small で約 500MB）。

## 使い方

### Web 画面

```bash
uvicorn main:app --reload
# → http://localhost:8000 を開き、URL を入力して「文字起こし開始」
```

### コマンドライン

```bash
# 標準出力にテキストを表示
python cli.py "https://example.com/article-with-video"

# タイムスタンプ付き
python cli.py "https://www.youtube.com/watch?v=XXXX" -t

# SRT 字幕ファイルとして out/ に保存、日本語・高精度モデルを指定
python cli.py "https://example.com/page" -f srt -o out/ -l ja -m medium

# 既存字幕を無視して必ず Whisper で文字起こし
python cli.py "https://example.com/page" --no-subtitles
```

| オプション | 説明 |
|---|---|
| `-f, --format` | `txt`（既定） / `srt` / `vtt` / `json` |
| `-o, --output-dir` | 保存先フォルダ（省略時は画面に表示） |
| `-l, --language` | 言語コード（`ja`, `en` など）。省略時は自動判定 |
| `-m, --model` | `tiny` / `base` / `small`（既定） / `medium` / `large-v3` |
| `--device` | `cpu`（既定） / `cuda`（NVIDIA GPU） |
| `--max-videos` | ページ内の動画を何本まで処理するか |
| `-t, --timestamps` | txt 出力に `[00:01:23]` 形式の時刻を付ける |

## 制限事項・注意

- **ログインが必要な動画**、**DRM 保護された動画**（Netflix 等の有料配信）は取得できません。
- JavaScript で後から読み込まれる動画は、yt-dlp が対応していないサイトだと検出できない場合があります。
- CPU での文字起こしは時間がかかります（目安: `small` で動画の長さの 0.3〜1 倍程度）。急ぐ場合は `-m tiny`、精度重視なら `-m medium` 以上を使ってください。
- 動画の利用は各サイトの利用規約・著作権の範囲内で行ってください。

## ファイル構成

```
video-transcriber/
├── transcriber.py   # コア処理（検出・字幕取得・Whisper・出力変換）
├── cli.py           # コマンドライン版
├── main.py          # Web 版（FastAPI）
└── static/index.html
```

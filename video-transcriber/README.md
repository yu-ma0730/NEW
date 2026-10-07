# 🎬 動画文字起こしツール（Video Transcriber）

Web ページの URL を渡すと、ページ内の動画を自動で見つけて文字起こしします。

## かんたん手順（Claude に頼む場合）

プログラミングの知識がなくても、次の流れで使えます。

1. claude.ai/code でこのリポジトリの新しいセッションを開く
2. 文字起こししたいページの URL を貼って「**この動画を文字起こしして**」と送る
3. 「ページに届かない」と言われたら、画面上部のタイトル横の ⌄ →「**クラウド環境を編集**」→
   「ネットワークアクセス」を **Full** にして「**変更を保存**」→ Claude に「設定しました」と送る
4. 15〜20 分ほど待つと（23 分の動画の場合）、文字起こしのファイルが届く
5. 終わったら、ネットワークアクセスを **Trusted** に戻す

セッション開始時に必要な部品が自動で入り（`.claude/hooks/session-start.sh`）、手順は
`.claude/skills/transcribe-video/SKILL.md` に書いてあるので、Claude が毎回同じやり方で作業します。

## 仕組み

1. **動画の検出**: [yt-dlp](https://github.com/yt-dlp/yt-dlp)（YouTube・Vimeo・ニコニコ等 1000 以上のサイトに対応）でページを解析。
   対応外のページは HTML を解析し、`<video>` / `<source>` / `og:video` / 埋め込み iframe / スクリプト内の `.mp4`・`.m3u8` を探します。
   それでも見つからなければ **ヘッドレスブラウザ（Playwright）で実際にページを開き、再生ボタンを押して** 読み込まれた動画（`.m3u8` / `.mp4` 等）を通信から拾います。
   UTAGE などの LP・会員サイト作成ツールのように、JavaScript で動画プレイヤーを組み立てるページ向けです。
2. **字幕があれば字幕を使用**（公式字幕 → 自動字幕の順）。速くて無料、精度も高めです。
3. **字幕が無ければ音声だけをダウンロード**し、[faster-whisper](https://github.com/SYSTRAN/faster-whisper)（Whisper）でローカル PC 上で音声認識します。外部 API キーは不要です。
4. `txt` / `srt` / `vtt` / `json` で出力します。

## セットアップ

```bash
cd video-transcriber
pip install -r requirements.txt
playwright install chromium   # JavaScript で動画を読み込むページ用
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

# UTAGE などのページ（JavaScript で読み込まれる動画も自動で探します）
python cli.py "https://utage-system.com/p/XXXXXXXX" -t -o out/

# 全形式（txt / タイムスタンプ付き txt / srt / vtt / json）をまとめて out/ に保存
python cli.py "https://example.com/page" -f all -l ja

# 既存字幕を無視して必ず Whisper で文字起こし
python cli.py "https://example.com/page" --no-subtitles
```

| オプション | 説明 |
|---|---|
| `-f, --format` | `txt`（既定） / `srt` / `vtt` / `json` / `all`（全形式を保存） |
| `-o, --output-dir` | 保存先フォルダ（省略時は画面に表示） |
| `-l, --language` | 言語コード（`ja`, `en` など）。省略時は自動判定 |
| `-m, --model` | `tiny` / `base` / `small`（既定） / `medium` / `large-v3` |
| `--device` | `cpu`（既定） / `cuda`（NVIDIA GPU） |
| `--no-browser` | ヘッドレスブラウザによる解析を行わない（高速化したい場合） |
| `--max-videos` | ページ内の動画を何本まで処理するか |
| `-t, --timestamps` | txt 出力に `[00:01:23]` 形式の時刻を付ける |

## 制限事項・注意

- **ログインが必要な動画**、**DRM 保護された動画**（Netflix 等の有料配信）は取得できません。
- 会員限定ページなど **ログイン後に見られる動画** は、このツールからは取得できません。
- 再生ボタンの形が特殊なプレイヤーでは、ブラウザ解析でも動画を拾えない場合があります。
- CPU での文字起こしは時間がかかります（目安: `small` で動画の長さの 0.3〜1 倍程度）。急ぐ場合は `-m tiny`、精度重視なら `-m medium` 以上を使ってください。
- 動画の利用は各サイトの利用規約・著作権の範囲内で行ってください。

## ファイル構成

```
video-transcriber/
├── transcriber.py   # コア処理（検出・字幕取得・Whisper・出力変換）
├── cli.py           # コマンドライン版
├── main.py          # Web 版（FastAPI）
├── static/index.html
└── tests/           # 単体テスト（python -m pytest -q tests）
```

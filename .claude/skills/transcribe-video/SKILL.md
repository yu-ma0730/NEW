---
name: transcribe-video
description: Web ページ（UTAGE の LP・YouTube・Vimeo・独自プレイヤーなど）にある動画を文字起こしして、txt/srt/vtt/json ファイルでユーザーに渡す。ユーザーが URL を貼って「文字起こしして」「この動画の内容を文字にして」などと頼んだときに使う。
---

# ページ内動画の文字起こし

ツール本体は `video-transcriber/`（`cli.py` / `transcriber.py`）。ユーザーはプログラミングに詳しくないので、
説明は専門用語を避けた日本語で、短く、次に何が起きるかを伝える。

## 手順

1. **接続確認**（URL のホストに届くか）
   ```bash
   curl -s -o /dev/null -w '%{http_code}\n' -m 15 -A Mozilla/5.0 "<URL>"
   curl -s -o /dev/null -w '%{http_code}\n' -m 15 https://huggingface.co
   ```
   `000` ならネットワーク設定でブロックされている。ユーザーに次を案内して、変更後に再確認する:
   画面上部のタイトル横の ⌄ →「クラウド環境を編集」→「ネットワークアクセス」を **Full** →「変更を保存」。
   （動画の配信元ドメインは事前に分からないため、カスタムより Full の方が往復が少ない。）
   設定変更は今のセッションにもすぐ反映される。

2. **文字起こし**（23 分の動画で 15〜20 分ほどかかるのでバックグラウンド実行）
   ```bash
   cd video-transcriber && python3 cli.py "<URL>" -f all -l ja -o out/
   ```
   - 精度を上げたいと言われたら `-m medium`（2〜3 倍遅い）。急ぐなら `-m tiny`。
   - 日本語以外の動画なら `-l` を外す（自動判定）。

3. **結果を渡す**: `out/` の `*_timestamps.txt`（一番読みやすい）・`.txt`・`.srt` を SendUserFile で送る。
   チャットに全文を貼らない。機械の聞き取りなので固有名詞や数字に誤りがあり得ると一言添える。

4. **後片付け**: ユーザーに、ネットワークアクセスを「Trusted」に戻すよう案内する（続けて別の URL を
   処理するなら Full のままでよい）。`out/` は .gitignore 済みなのでコミットしない。

## つまずきやすい点（過去に実際に起きたこと）

- **UTAGE のページ**は `<title>` が空で、動画は JSON 内に `"src":"https:\/\/...wasabisys.com\/...\/video.m3u8"`
  とエスケープされて埋め込まれている。`find_media_in_html` はこれを戻して探し、同じ JSON の `"title"` を題名に使う。
- **ログインが必要なページ**（会員サイト）は取得できない。その場合は正直にそう伝える。
- 文字起こしが `av.open() got an unexpected keyword argument` で落ちる場合は PyAV のバージョン差。
  `transcriber._decode_audio` で ffmpeg デコードしているので通常は起きないが、変更時は注意。
- 動画が見つからないときは `python3 -c "import transcriber as t; print(t.find_media_in_html('<URL>'))"` で
  HTML から何が拾えているか確認し、`curl` でページを保存して `m3u8|mp4|vimeo|youtube|player` を grep する。
  新しいパターンを見つけたら `transcriber.py` に対応を足し、`tests/` にテストを追加する。

## 開発時の確認

```bash
cd video-transcriber && python3 -m pytest -q tests && ruff check .
```

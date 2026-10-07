#!/bin/bash
# クラウドセッション開始時に、動画文字起こしツールの依存関係を入れる
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

cd "$CLAUDE_PROJECT_DIR/video-transcriber"

# pip install は入っていれば何もしないので、何度実行しても安全
pip install -q --disable-pip-version-check -r requirements.txt pytest ruff

# 音声の変換に ffmpeg が必要（通常はクラウド環境に最初から入っている）
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ffmpeg が見つかりません。文字起こしの前にインストールが必要です" >&2
fi

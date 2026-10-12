#!/bin/sh
# profile-form.html から、普通のWebページとして開ける docs/index.html を作る。
# （claude.ai の公開ページは表示時にHTMLの頭の部分を自動で足すため、元ファイルには無い）
# 使い方：リポジトリのどこからでも  sh gunshi/tools/build-web.sh
set -e
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SRC="$ROOT/gunshi/profile-form.html"
OUT="$ROOT/docs/index.html"
mkdir -p "$ROOT/docs"
{
  printf '%s\n' '<!doctype html>' '<html lang="ja">' '<head>' '<meta charset="utf-8">' \
    '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">' \
    '<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0;font-size:14px}img{max-width:100%}[hidden]{display:none!important}</style>' \
    '</head>' '<body>'
  cat "$SRC"
  printf '%s\n' '</body>' '</html>'
} > "$OUT"
echo "作成しました: $OUT"

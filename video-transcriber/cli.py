"""コマンドラインから使う場合のエントリポイント。

例:
    python cli.py https://example.com/page-with-video
    python cli.py https://www.youtube.com/watch?v=xxxx -f srt -o out/
"""

import argparse
import re
import sys
from pathlib import Path

import transcriber


def safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("_")[:80] or "transcript"


def main() -> int:
    p = argparse.ArgumentParser(description="Web ページ内の動画を文字起こしします")
    p.add_argument("url", help="動画を含むページ（または動画）の URL")
    p.add_argument("-f", "--format", choices=["txt", "srt", "vtt", "json", "all"], default="txt",
                   help="all を指定すると全形式（タイムスタンプ付き txt を含む）を保存します")
    p.add_argument("-o", "--output-dir", type=Path, help="出力先ディレクトリ（省略時は標準出力）")
    p.add_argument("-l", "--language", help="言語コード（例: ja, en）。省略時は自動判定")
    p.add_argument("-m", "--model", default="small",
                   help="Whisper モデル: tiny/base/small/medium/large-v3（大きいほど高精度・低速）")
    p.add_argument("--device", default="cpu", help="cpu または cuda")
    p.add_argument("--no-subtitles", action="store_true", help="既存字幕を使わず必ず Whisper で文字起こし")
    p.add_argument("--no-browser", action="store_true",
                   help="ヘッドレスブラウザでのページ解析（JavaScript で読み込む動画の検出）を行わない")
    p.add_argument("--max-videos", type=int, help="処理する動画数の上限")
    p.add_argument("-t", "--timestamps", action="store_true", help="txt 出力にタイムスタンプを付ける")
    args = p.parse_args()
    if args.format == "all" and not args.output_dir:
        args.output_dir = Path("out")

    log = lambda msg: print(msg, file=sys.stderr)
    try:
        results = transcriber.transcribe_page(
            args.url,
            max_videos=args.max_videos,
            use_browser=not args.no_browser,
            language=args.language,
            model_size=args.model,
            device=args.device,
            use_subtitles=not args.no_subtitles,
            log=log,
        )
    except Exception as e:  # noqa: BLE001 - CLI ではメッセージだけ見せる
        log(f"エラー: {e}")
        return 1

    for i, t in enumerate(results, 1):
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            stem = args.output_dir / f"{i:02d}_{safe_name(t.title)}"
            if args.format == "all":
                outputs = {f".{f}": transcriber.render(t, f) for f in ("txt", "srt", "vtt", "json")}
                outputs["_timestamps.txt"] = transcriber.render(t, "txt", timestamps=True)
            else:
                outputs = {f".{args.format}": transcriber.render(t, args.format, args.timestamps)}
            for suffix, body in outputs.items():
                path = stem.with_name(stem.name + suffix)
                path.write_text(body, encoding="utf-8")
                log(f"保存しました: {path}  （方式: {t.method}）")
        else:
            out = transcriber.render(t, args.format, args.timestamps)
            if len(results) > 1:
                print(f"===== {t.title} =====")
            print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

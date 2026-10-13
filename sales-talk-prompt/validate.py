"""セールストーク出力(JSON)の文字数とNGワードを検証する。

使い方:
    python validate.py output.json
    cat output.json | python validate.py -
"""

import json
import sys

# 根拠がなければ使えない・原則使えない表現（簡易チェック。最終判断は人が行う）
NG_WORDS = [
    "絶対", "必ず", "100%", "１００％", "誰でも", "完全", "永久",
    "No.1", "NO.1", "ナンバーワン", "日本一", "世界一", "業界最安", "最安値", "最高品質",
    "治る", "治す", "痩せる", "シミが消える", "若返る", "免疫力", "元本保証", "必ず儲かる",
]


def validate(data):
    errors, warnings = [], []
    total = 0
    for part, sentences in (data.get("talk") or {}).items():
        for i, s in enumerate(sentences or []):
            text, limit = s.get("text", ""), s.get("limit")
            n = len(text)
            total += n
            if s.get("chars") != n:
                warnings.append(f"{part}[{i}] 自己申告 {s.get('chars')} 字 / 実測 {n} 字")
            if limit is not None and n > limit:
                errors.append(f"{part}[{i}] {n} 字 > 上限 {limit} 字: {text}")
            for w in NG_WORDS:
                if w in text:
                    warnings.append(f"{part}[{i}] 要確認ワード「{w}」: {text}")
    return total, errors, warnings


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "-"
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    total, errors, warnings = validate(json.loads(raw))
    print(f"合計 {total} 字")
    for e in errors:
        print("NG  ", e)
    for w in warnings:
        print("WARN", w)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()

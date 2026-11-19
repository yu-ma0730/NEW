# 🕷️ Books Scraper（Webスクレイピング自動化ツール）

スクレイピング練習用サイト [Books to Scrape](https://books.toscrape.com/) から、
**全50カテゴリ・1000冊**の書籍情報を自動で集めて **CSV / JSON** に保存する Python ツールです。

集めたデータは [Book Explorer](../book-explorer/)（ツール3）で検索・可視化できます。

## 🎯 できること

- 全カテゴリの一覧ページを自動でめくり、次の項目を取得
  - 書名 / カテゴリ / 価格 / 評価（1〜5） / 在庫の有無 / 商品URL / 画像URL
- CSV（Excel で開いても文字化けしない形式）と JSON の両方で保存
- 取得件数・所要時間をログで表示

## 🛡️ 行儀のよいスクレイピングのための工夫

| 工夫 | 内容 |
|---|---|
| アクセス間隔 | 既定で 0.5 秒以上空けてアクセス（`--delay` で変更可） |
| 自動リトライ | 接続エラー・5xx・429 のときは間隔を空けて最大3回まで再挑戦 |
| robots.txt の確認 | サイトが禁止しているページにはアクセスしない |
| 部分的な失敗に強い | 1カテゴリで失敗しても全体は止めず、最後に失敗一覧を表示 |
| User-Agent の明示 | どのようなツールからのアクセスかを名乗る |

## 🚀 使い方

```bash
cd web-scraper
pip install -r requirements.txt

# 全件取得（約50秒）
python scraper.py

# 動作確認用に3カテゴリだけ取得
python scraper.py --max-categories 3

# 保存先とアクセス間隔を指定
python scraper.py --output-dir output --delay 1.0
```

結果は `output/books.csv` と `output/books.json` に保存されます。

### オプション

| オプション | 既定値 | 説明 |
|---|---|---|
| `--output-dir` | `output` | 保存先フォルダ |
| `--delay` | `0.5` | アクセス間隔（秒） |
| `--max-categories` | なし（全件） | 取得するカテゴリ数の上限 |
| `-v`, `--verbose` | オフ | アクセスしたURLも表示 |

### 出力例（CSV）

```csv
title,category,price,rating,in_stock,url,image_url
It's Only the Himalayas,Travel,45.17,2,True,https://books.toscrape.com/catalogue/its-only-the-himalayas_981/index.html,...
```

## 🧪 テスト

ネットワークに接続せずに、HTML の読み取りと保存処理をテストします。

```bash
cd web-scraper
python -m unittest discover -s tests -v
```

## 🧱 構成

```
web-scraper/
├── scraper.py          # 本体（取得・解析・保存）
├── requirements.txt    # 必要なパッケージ
└── tests/
    └── test_scraper.py # 単体テスト
```

`scraper.py` は「HTMLの解析」「取得」「保存」を分けて書いているので、
対象サイトを変えるときは主に `parse_*` 関数を書き換えるだけで済みます。

## 💻 技術スタック

- Python（3.13 で動作確認済み）
- [requests](https://pypi.org/project/requests/) 2.32.3 — HTTP 通信
- [beautifulsoup4](https://pypi.org/project/beautifulsoup4/) 4.12.3 — HTML 解析

## ⚠️ 注意

- Books to Scrape はスクレイピング練習用のデモサイトで、価格・評価は架空の値です。
- 実在のサイトをスクレイピングする場合は、利用規約と robots.txt を必ず確認してください。

## 📄 ライセンス

MIT License

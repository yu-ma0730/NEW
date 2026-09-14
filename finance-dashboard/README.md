# 📊 金融データ可視化ダッシュボール

複数の銘柄の株価をリアルタイム表示し、ポートフォリオ管理ができるダッシュボードツールです。

## 🎯 機能

✅ **リアルタイム株価表示** - 複数銘柄の株価を一覧表示
✅ **詳細チャート** - 各銘柄の価格変動をグラフで可視化
✅ **ポートフォリオ管理** - 保有株の評価損益を自動計算
✅ **レスポンシブデザイン** - PC/モバイル対応
✅ **API ベース** - 拡張性の高い REST API 設計

## 🚀 使い方

### 1. インストール

```bash
cd finance-dashboard
pip install -r requirements.txt
```

### 2. 起動

```bash
python main.py
```

ブラウザで `http://localhost:8000` を開いてください。

### 3. API エンドポイント

| エンドポイント | 説明 |
|---|---|
| `GET /api/stocks` | 全銘柄の株価一覧 |
| `GET /api/stock/{symbol}` | 特定銘柄の詳細情報 |
| `GET /api/portfolio` | ポートフォリオ情報 |

### レスポンス例

```json
{
  "stocks": [
    {
      "symbol": "AAPL",
      "name": "Apple Inc.",
      "price": 189.45,
      "change": 2.50,
      "changePercent": 1.34
    }
  ],
  "success": true
}
```

## 📝 カスタマイズ

### 株価データの追加

`main.py` の `DEMO_DATA` を編集して、銘柄やデータを追加できます。

```python
DEMO_DATA = {
    "AAPL": {
        "name": "Apple Inc.",
        "price": 189.45,
        "change": 2.50,
        "changePercent": 1.34,
        "history": [...]
    },
    # 新しい銘柄を追加
    "NFLX": {
        "name": "Netflix Inc.",
        "price": 280.50,
        "change": 5.20,
        "changePercent": 1.87,
        "history": [...]
    }
}
```

### 本物の API データを使用

Alpha Vantage や Finnhub などの API と統合するには：

1. API キーを取得
2. `.env` ファイルに設定
3. `main.py` で API 呼び出しに変更

## 🔌 拡張機能（将来対応）

- [ ] リアルタイム更新（WebSocket）
- [ ] 複数通貨対応
- [ ] テクニカル分析指標
- [ ] アラート機能
- [ ] ユーザー認証
- [ ] データベース保存

## 💻 技術スタック

- **バックエンド**：Python + FastAPI
- **フロントエンド**：HTML5 + CSS3 + JavaScript
- **チャート**：Chart.js
- **API**：RESTful API（JSON）

## 📦 依存パッケージ

- fastapi==0.104.1
- uvicorn==0.24.0
- python-dotenv==1.0.0
- requests==2.31.0
- aiohttp==3.9.0
- pydantic==2.5.0

## 🎨 スクリーンショット

### ダッシュボード画面
- リアルタイム株価一覧
- ポートフォリオ総資産表示
- 評価損益の自動計算

### 詳細モーダル
- 銘柄ごとの価格推移チャート
- 5日間の履歴表示
- インタラクティブなグラフ

## ⚠️ 注意

**現在はデモデータを使用しています。**

本格的な運用には以下が必要です：
- 金融データ API との統合
- リアルタイム更新機能
- 定期的なデータ更新スケジューラ
- エラーハンドリング

## 📄 ライセンス

MIT License

## 🤝 貢献

改善提案やバグ報告は GitHub Issues でお願いします。

---

**作成日**：2026年9月14日
**ステータス**：プロトタイプ版

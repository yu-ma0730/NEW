# Threads 全自動モード（セルフホスト版）

[BBB](https://bbb-asp.com/) の「全自動モード」（`/threads/auto`、ログインが必要）を、公開情報から推測して作ったセルフホスト版です。
テーマと投稿頻度を決めると、Claude が投稿文を作り、Meta 公式の Threads API で決めた時刻に投稿し続けます。

> 元ページはログインしないと見られないため、画面そのものは確認していません。
> 仕様は BBB の公開ページ（[トップ](https://bbb-asp.com/)・[予約投稿ガイド](https://bbb-asp.com/articles/threads-scheduled-post-bbb-guide)・[無料で始める方法](https://bbb-asp.com/articles/threads-auto-post-free)）に書かれている内容をもとにしています。

## 機能

| 機能 | 動き |
|---|---|
| 投稿スケジュール | 1日1〜3回。指定時刻 ± ゆらぎ幅（例: 12:30 ± 15分 → 12:15〜12:45） |
| 投稿内容 | トーン（カジュアル／ビジネス／ユーモア／インスピレーション）、テーマ、追加指示、お手本サンプル |
| スレッド形式 | 1本目に返信（`reply_to_id`）をつないで連投。最大本数を指定可能 |
| CTA セルフリプライ | 公開の数分後に、最後の投稿へ返信（最大500文字） |
| トピックタグ | 付けない／固定／AI に選ばせる（`topic_tag`、50文字以内・`.` と `&` は不可） |
| 品質ゲート | AI が 0〜100 で採点。合格点未満なら作り直し、全部不合格なら最高得点の案を使う |
| 初速バズ検知 | 公開1〜6時間の投稿を30分ごとに確認。閲覧数の伸びが過去投稿の中央値の2倍以上なら 🔥（過去データ5件以上が必要） |
| バズ投稿リサイクル | 🔥 の付いた投稿を（既定で7日以上たってから）言い換えて再投稿 |
| アカウント保護 | 既定で24時間あたり25件まで・投稿間隔20分以上。上限に達したらエラーにせず待つ |
| プレビュー | 保存前に生成結果を確認し、そのまま手動で投稿することもできる |
| DRY_RUN | Threads に連携していない間はログに出すだけ（実際には投稿しない） |

## セットアップ

```bash
cd threads-auto
pip install -r requirements.txt
cp .env.example .env   # 各キーを記入
uvicorn main:app --port 8000
# → http://localhost:8000
```

1. **Meta アプリを作る**: [Meta for Developers](https://developers.facebook.com/) で、ユースケースに「Threads API」を選んでアプリを作成します。
   審査を受けていないアプリでも、アプリのテスターに追加したアカウントには投稿できます（[公式ドキュメント](https://developers.facebook.com/docs/threads/posts)）。
   リダイレクトコールバック URL には `THREADS_REDIRECT_URI` と同じ値を登録してください。
2. `.env` に `THREADS_APP_ID` / `THREADS_APP_SECRET` / `ANTHROPIC_API_KEY` を書き、画面の「Threads と連携する（OAuth）」を押します。
   長期トークン（60日有効）を取得して保存し、30日たったら自動で更新します。
3. 動作を確認したら `DRY_RUN=false` にして再起動し、「全自動モード: ON」にします。

## 構成

| ファイル | 役割 |
|---|---|
| `main.py` | FastAPI（設定 API・プレビュー・OAuth）と、バックグラウンドで動くワーカー |
| `engine.py` | 30秒ごとの処理: スロット消化 → CTA 返信 → バズ検知 → トークン更新 |
| `scheduling.py` | ゆらぎ付きの投稿時刻、24時間の上限と投稿間隔、バズ判定 |
| `generator.py` | Claude（`claude-opus-5-5`、構造化出力）で投稿生成・採点・言い換え |
| `threads_api.py` | Threads API（投稿・返信・OAuth・トークン更新・インサイト・上限確認） |
| `store.py` | SQLite（設定・投稿履歴・スロット） |
| `static/index.html` | 設定画面 |

## Threads API の参照元（Meta 公式）

- 投稿（コンテナ作成 → `threads_publish`、500文字、250件/24時間、公開前に約30秒待つ推奨）: https://developers.facebook.com/docs/threads/posts
- 返信（`reply_to_id`）: https://developers.facebook.com/docs/threads/reference/publishing
- 上限の確認（`threads_publishing_limit`、返信は1000件/24時間）: https://developers.facebook.com/docs/threads/troubleshooting
- OAuth: https://developers.facebook.com/docs/threads/get-started/get-access-tokens-and-permissions
- 長期トークン（60日・更新）: https://developers.facebook.com/docs/threads/get-started/long-lived-tokens
- インサイト（views / likes / replies / reposts）: https://developers.facebook.com/docs/threads/insights

## テスト

```bash
python -m pytest -q tests
```

## 注意

- 自動投稿のペースは控えめにしてありますが、Threads 側がアカウントをどう判断するかまでは保証できません。
- 1アカウント用です。BBB にある複数アカウント、RSS、X アダプター、トレンド提案、画像投稿はまだありません。

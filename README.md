# co-cook 🍳

個人用の **AIメニュー提案＆フィードバック・インジェストアプリ** の MVP。

「今日の気分・条件」を入力すると、過去のフィードバックから学習した **「我が家の好み」** を踏まえて Gemini が献立を提案します。提案へのフィードバックを溜め、ボタン一つで好みを継続学習（インジェスト）していく、1画面完結の SSR アプリです。

- **バックエンド**: FastAPI + SQLAlchemy 2.0 + SQLite
- **フロント**: Jinja2 テンプレート（SSR）+ Tailwind CSS（CDN）
- **AI**: Google Gemini（`google-genai` SDK）

---

## 3層アーキテクチャ

データを性質の異なる3つの層に分離し、「層をまたぐ鉄則」に沿って一方向に流します。

| 層 | テーブル | 性質 | 役割 |
|----|----------|------|------|
| 生ソース層 | `menu_logs` | イミュータブル | 提案とフィードバックの生ログ |
| サマリー層 | `menu_summaries` | ほぼイミュータブル | 1回分の「提案＋FB」の客観要約 |
| ページ・ストック層 | `menu_essences` | 常に更新される生きたデータ | 「我が家の好み」のエッセンス |

**層をまたぐ鉄則（インジェストの流れ）:**

```
menu_logs(unprocessed) ──要約──▶ menu_summaries ──反映──▶ menu_essences(上書き)
        └────────────────────── status を ingested へ ──────────────────────┘
```

`menu_essences` のカテゴリ（`key`）:

| key | 内容 |
|-----|------|
| `flavor_preference` | 味の好み |
| `disliked_ingredients` | 苦手な食材・NG |
| `favorite_menus` | お気に入りメニュー |
| `presentation_preference` | 提案の伝え方・形式（文量・前置き・結論先行など） |

---

## セットアップ

前提: Python 3.10 以上。

```bash
# 1. 仮想環境と依存関係
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 2. APIキーを設定（.env は gitignore 済み）
cp .env.example .env
#   .env を開いて GEMINI_API_KEY に自分のキーを記入
#   キーの取得: https://aistudio.google.com/apikey

# 3. 起動（.env は自動で読み込まれます）
uvicorn main:app --reload
```

ブラウザで <http://127.0.0.1:8000> を開く。

---

## 使い方

1. **提案** — 「今日の気分・条件」を入力 → `menu_logs` に `unprocessed` で保存され、画面に提案が出ます。
2. **フィードバック** — 未処理ログにクイックボタン（👍 / 重すぎた / 好みでない）か自由入力でフィードバックを送信。
3. **学習（インジェスト）** — 「🧠 我が家の好みを学習する」を押すと、フィードバック済みの未処理ログを要約 → エッセンスへ反映し、ログを `ingested` に遷移します。

> POST 後はすべて `/` へリダイレクト（PRG パターン）するため、リロードによる二重送信は起きません。

---

## 設定

| 環境変数 | 説明 |
|----------|------|
| `GEMINI_API_KEY` | Gemini API キー（**必須**）。`.env` から読み込み |

使用モデルは `gemini_service.py` の `MODEL` 定数で変更できます。

---

## プロジェクト構成

```
co-cook/
├── main.py              # FastAPI ルーティング + SSR 描画（PRG）
├── models.py            # 3層のデータモデル
├── database.py          # SQLite 接続・セッション
├── gemini_service.py    # Gemini ラッパー（提案 / 要約 / エッセンス更新）
├── templates/index.html # 1画面 SSR（Tailwind CDN）
├── requirements.txt
├── .env.example         # APIキーのテンプレート（.env は作成して使う）
└── .gitignore
```

---

## ライセンス / 著作権

Copyright © 2026 craftpaperbag. **All rights reserved.（無断転載・複製・再配布を禁じます）**

本リポジトリは閲覧目的で公開していますが、著作権はすべて作者が留保します。オープンソースライセンスは付与していません。利用・改変・再配布をご希望の場合は作者の許諾を得てください。

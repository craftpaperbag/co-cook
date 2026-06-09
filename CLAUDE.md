# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

co-cook は個人用の AI メニュー提案アプリ。条件を入力すると、過去のフィードバックから学習した「我が家の好み」を踏まえて Gemini が献立を提案し、フィードバックを溜めて好みを継続学習（インジェスト）する。FastAPI + Jinja2 (SSR) + SQLite の 1 画面完結アプリ。

## コマンド

```bash
# セットアップ
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # GEMINI_API_KEY を記入（必須・gitignore 済み）

# 起動（.env は main.py が load_dotenv() で自動読込）
.venv/bin/uvicorn main:app --reload   # http://127.0.0.1:8000
```

テストフレームワークは未導入。起動せずに動作確認したい場合は `TestClient` を使う:

```bash
.venv/bin/python -c "from fastapi.testclient import TestClient; import main; \
print(TestClient(main.app).get('/').status_code)"
```

## アーキテクチャ：3層 + インジェストの一方向フロー

このアプリの核心は、データを性質の異なる 3 層に分離し、一方向にしか流さないこと（`models.py` の docstring が出典）。層を逆流させたり、生ログを直接「好み」に混ぜたりしてはいけない。

| 層 | テーブル / モデル | 性質 | 役割 |
|----|------|------|------|
| 生ソース層 | `menu_logs` / `MenuLog` | イミュータブル | 提案＋フィードバックの生ログ。`status` は `unprocessed`→`ingested` |
| サマリー層 | `menu_summaries` / `MenuSummary` | ほぼイミュータブル | ログ 1 件を客観要約したもの |
| ページ・ストック層 | `menu_essences` / `MenuEssence` | 常に更新 | 「我が家の好み」。インジェストのたびに value を上書き |

**インジェストの流れ**（`main.py` の `/ingest`、層をまたぐ鉄則）:

```
menu_logs(unprocessed かつ feedback あり)
  ──ステップA: summarize_log──▶ menu_summaries を追加
  ──ステップB: update_essences──▶ menu_essences を上書き
  ──対象ログの status を ingested へ遷移──
```

この一連は単一トランザクションで、AI 呼び出しを含むため例外時は `db.rollback()` する。

### モジュール構成と役割分担

- `main.py` — FastAPI ルーティングと SSR 描画。ルートは `/`（表示）/ `/propose` / `/feedback/{log_id}` / `/ingest`。**全 POST は PRG パターン**で `/` へ 303 リダイレクト（リロードによる提案/学習の二重実行を防ぐ）。flash メッセージはクエリ文字列で次の GET に 1 回だけ引き継ぐ。
- `gemini_service.py` — Gemini ラッパー。AI 操作は `propose_menu` / `summarize_log`（ステップA）/ `update_essences`（ステップB）の 3 つだけ。ここ以外から SDK を直接呼ばない。
- `models.py` / `database.py` — 3層モデルと SQLite 接続。`init_db()` は起動時 lifespan で一度だけ呼ばれる。
- `templates/index.html` — 1 画面の本体（提案・フィードバック・学習・好みの表示）。

### 「我が家の好み」のカテゴリは ESSENCE_KEYS が単一の真実

`gemini_service.ESSENCE_KEYS`（`flavor_preference` / `disliked_ingredients` / `favorite_menus` / `presentation_preference`）が好みカテゴリの定義。プロンプトの JSON 雛形・カテゴリ一覧・`main.py` のエッセンス読み書きがすべてこの辞書から導出される。カテゴリを増減するときはここだけを変更する。`presentation_preference` は「味」ではなく提案の伝え方・出力形式の好みを保持する点に注意。

`update_essences` は AI に JSON を返させて取り込むが、JSON パースに失敗したら既存値を維持する（破壊的更新を避ける防御）。

## 注意点

- DB は単一ファイル `co_cook.db`。スキーマ変更時のマイグレーション機構はなく、`create_all` のみ（既存テーブルは作り直されない）。**`co_cook.db` を削除・上書きすると学習済みの「我が家の好み」が消える。**
- 使用モデルは `gemini_service.MODEL` 定数で切り替える。

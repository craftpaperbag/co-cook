"""AIメニュー提案＆フィードバック・インジェストアプリ（MVP）。

FastAPI + Jinja2 (SSR) + Tailwind(CDN) + SQLite + Gemini。
1 画面で「提案 → フィードバック → 学習(インジェスト)」が完結する。
"""

from contextlib import asynccontextmanager
from urllib.parse import quote

from dotenv import load_dotenv

# .env からの環境変数読み込み（GEMINI_API_KEY 等）。アプリ起動方法に依らず
# キーを拾えるよう、他モジュールのインポート前に実行する。
load_dotenv()

from fastapi import Depends, FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

import gemini_service
from database import get_db, init_db
from models import (
    STATUS_INGESTED,
    STATUS_UNPROCESSED,
    MenuEssence,
    MenuLog,
    MenuSummary,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="co-cook", lifespan=lifespan)
templates = Jinja2Templates(directory="templates")


# ---- ヘルパ ---------------------------------------------------------------
def load_essences(db: Session) -> dict[str, str]:
    """全エッセンスを key -> value の辞書で取得する。"""
    rows = db.scalars(select(MenuEssence)).all()
    essences = {key: "" for key in gemini_service.ESSENCE_KEYS}
    for row in rows:
        essences[row.key] = row.value
    return essences


def save_essences(db: Session, essences: dict[str, str]) -> None:
    """エッセンスを upsert で上書き保存する。"""
    for key, value in essences.items():
        row = db.get(MenuEssence, key)
        if row is None:
            db.add(MenuEssence(key=key, value=value))
        else:
            row.value = value
    db.commit()


def render_index(
    request: Request, db: Session, *, flash: str | None = None
) -> HTMLResponse:
    """トップ画面を描画する。"""
    unprocessed_logs = (
        db.scalars(
            select(MenuLog)
            .where(MenuLog.status == STATUS_UNPROCESSED)
            .order_by(MenuLog.timestamp.desc())
        ).all()
    )
    ingested_logs = (
        db.scalars(
            select(MenuLog)
            .where(MenuLog.status == STATUS_INGESTED)
            .order_by(MenuLog.timestamp.desc())
        ).all()
    )
    essences = load_essences(db)
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "unprocessed_logs": unprocessed_logs,
            "ingested_logs": ingested_logs,
            "essences": essences,
            "essence_labels": gemini_service.ESSENCE_KEYS,
            "flash": flash,
        },
    )


def redirect_with_flash(message: str) -> RedirectResponse:
    """POST 処理後に PRG パターンで `/` へ 303 リダイレクトする。

    リロードによるフォーム再送信（提案/学習の二重実行）を防ぐ。
    flash メッセージはクエリ文字列で 1 回だけ次の GET に引き継ぐ。
    """
    return RedirectResponse(f"/?flash={quote(message)}", status_code=303)


# ---- 画面表示 -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def index(
    request: Request, flash: str | None = None, db: Session = Depends(get_db)
):
    return render_index(request, db, flash=flash)


# ---- 1. メニュー提案 ------------------------------------------------------
@app.post("/propose", response_class=HTMLResponse)
def propose(
    request: Request,
    context: str = Form(...),
    db: Session = Depends(get_db),
):
    essences = load_essences(db)
    try:
        proposed = gemini_service.propose_menu(context, essences)
    except Exception as exc:  # noqa: BLE001
        return redirect_with_flash(f"提案の生成に失敗しました: {exc}")

    log = MenuLog(
        context=context,
        proposed_menu=proposed,
        status=STATUS_UNPROCESSED,
    )
    db.add(log)
    db.commit()
    # proposed=1 を付け、GET 側で提案セクションへスクロールさせる。
    message = quote("新しいメニューを提案しました。")
    return RedirectResponse(f"/?flash={message}&proposed=1", status_code=303)


# ---- 2. フィードバック送信 ------------------------------------------------
@app.post("/feedback/{log_id}")
def submit_feedback(
    log_id: str,
    feedback: str = Form(...),
    db: Session = Depends(get_db),
):
    feedback = feedback.strip()
    log = db.get(MenuLog, log_id)
    if feedback and log is not None and log.status == STATUS_UNPROCESSED:
        log.feedback = feedback
        db.commit()
    return RedirectResponse("/", status_code=303)


# ---- 3. 学習（インジェスト） ---------------------------------------------
@app.post("/ingest", response_class=HTMLResponse)
def ingest(request: Request, db: Session = Depends(get_db)):
    # 層をまたぐ鉄則: 未処理かつフィードバックありのログのみ対象。
    target_logs = (
        db.scalars(
            select(MenuLog).where(
                MenuLog.status == STATUS_UNPROCESSED,
                MenuLog.feedback.is_not(None),
                MenuLog.feedback != "",
            )
        ).all()
    )
    if not target_logs:
        return redirect_with_flash(
            "学習対象（フィードバック済の未処理ログ）がありません。"
        )

    try:
        new_summaries: list[str] = []
        # ステップA: サマリー生成
        for log in target_logs:
            summary_text = gemini_service.summarize_log(
                log.proposed_menu, log.feedback or ""
            )
            db.add(MenuSummary(log_id=log.id, content=summary_text))
            new_summaries.append(summary_text)

        # ステップB: エッセンス更新
        current = load_essences(db)
        updated = gemini_service.update_essences(current, new_summaries)
        save_essences(db, updated)

        # 処理済へ遷移
        for log in target_logs:
            log.status = STATUS_INGESTED
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        return redirect_with_flash(f"学習に失敗しました: {exc}")

    return redirect_with_flash(f"{len(target_logs)} 件のログを学習しました。")


# ---- 4. ログの個別削除 ----------------------------------------------------
@app.post("/delete/{log_id}")
def delete_log(log_id: str, db: Session = Depends(get_db)):
    log = db.get(MenuLog, log_id)
    if log is None:
        return RedirectResponse("/", status_code=303)
    # FK 制約を避けるため、紐づくサマリーを先に削除する。
    summary = db.scalar(
        select(MenuSummary).where(MenuSummary.log_id == log_id)
    )
    if summary is not None:
        db.delete(summary)
    db.delete(log)
    db.commit()
    # 削除はログのみ。学習済みの「我が家の好み」（エッセンス）には影響しない。
    return redirect_with_flash(
        "ログを削除しました。「我が家の好み」は変更されていません。"
    )


# ---- 5. 「我が家の好み」の個別編集 ----------------------------------------
@app.post("/essence/{key}")
def update_essence(
    key: str, value: str = Form(""), db: Session = Depends(get_db)
):
    if key not in gemini_service.ESSENCE_KEYS:
        return RedirectResponse("/", status_code=303)
    value = value.strip()
    row = db.get(MenuEssence, key)
    if row is None:
        db.add(MenuEssence(key=key, value=value))
    else:
        row.value = value
    db.commit()
    label = gemini_service.ESSENCE_KEYS[key]
    return redirect_with_flash(f"「{label}」を更新しました。")

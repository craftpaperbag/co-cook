"""データモデル（3層アーキテクチャ）。

CLAUDE.md の思想に基づき、データを 3 つの層に分離する。

  1. MenuLog      … 生ソース層 / イミュータブル
                    （提案とフィードバックの生ログ。一度書いたら基本変更しない）
  2. MenuSummary  … サマリー層 / ほぼイミュータブル
                    （1回の「提案＋フィードバック」を客観要約したもの）
  3. MenuEssence  … ページ・ストック層 / 常に更新される生きたデータ
                    （我が家の好みのエッセンス。インジェストのたびに上書き）

層をまたぐ鉄則：
  生ソース(未処理) → サマリー生成 → エッセンス更新 → 生ソースを処理済へ
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---- ステータス定数 -------------------------------------------------------
STATUS_UNPROCESSED = "unprocessed"
STATUS_INGESTED = "ingested"


class MenuLog(Base):
    """生ソース層 / イミュータブル。

    AI の提案 1 件につき 1 行。フィードバックは後から 1 度だけ書き込まれ、
    インジェスト時に status が ingested へ遷移する。
    """

    __tablename__ = "menu_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=_now)
    context: Mapped[str] = mapped_column(Text)
    proposed_menu: Mapped[str] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_UNPROCESSED)

    summary: Mapped["MenuSummary | None"] = relationship(
        back_populates="log", uselist=False
    )


class MenuSummary(Base):
    """サマリー層 / ほぼイミュータブル。

    1 件の MenuLog（提案＋フィードバック）を客観的に要約したもの。
    """

    __tablename__ = "menu_summaries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    log_id: Mapped[str] = mapped_column(ForeignKey("menu_logs.id"))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    log: Mapped["MenuLog"] = relationship(back_populates="summary")


class MenuEssence(Base):
    """ページ・ストック層 / 常に更新される生きたデータ。

    key はカテゴリ（flavor_preference, disliked_ingredients, favorite_menus 等）。
    value はマークダウン箇条書きなどで表現された「我が家の好み」。
    インジェストのたびに value が上書き更新される。
    """

    __tablename__ = "menu_essences"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=_now, onupdate=_now
    )

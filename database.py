"""データベース接続とセッション管理。

SQLite を SQLAlchemy 2.0 スタイルで利用する。
3層アーキテクチャ（生ソース層 / サマリー層 / ページ・ストック層）の
永続化先として単一の SQLite ファイル `co_cook.db` を使用する。
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

# SQLite ファイルへの接続。
# check_same_thread=False は FastAPI のスレッドプールから同一接続を
# 触れるようにするための SQLite 固有の設定。
SQLALCHEMY_DATABASE_URL = "sqlite:///./co_cook.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """全モデルの基底クラス。"""


def get_db() -> Generator[Session, None, None]:
    """リクエストスコープの DB セッションを払い出す FastAPI 依存性。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """テーブルを作成する。アプリ起動時に一度だけ呼ぶ。"""
    # models をインポートしてメタデータにテーブルを登録する。
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)

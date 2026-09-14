from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from .config import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def q(db: Session, sql: str, **params):
    """짧은 raw SQL 헬퍼 — 대시보드 조회는 SQL 뷰 중심이라 ORM 모델 없이 간다."""
    return db.execute(text(sql), params)

"""SQLAlchemy database setup — SQLite for MVP, swap DATABASE_URL to PostgreSQL for prod."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session

from varos.config import settings

# Derive sync SQLite URL from the aiosqlite URL stored in settings
_db_url = settings.database_url.replace("sqlite+aiosqlite:///", "sqlite:///")

engine = create_engine(_db_url, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    """FastAPI dependency — yields a DB session and closes it after request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Create all tables. Called once on app startup."""
    from varos.api import models as _models  # noqa: F401 — registers ORM classes
    Base.metadata.create_all(bind=engine)

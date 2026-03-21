"""Database engine, session factory, and table creation."""

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


class Base(DeclarativeBase):
    pass


# Engine and SessionLocal are created lazily so tests can override DATABASE_URL
# before the module is first used.

_engine = None
_SessionLocal = None


def _get_engine():
    global _engine
    if _engine is None:
        from backend.config.settings import settings
        url = settings.database_url
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        else:
            kwargs["pool_size"] = 5
            kwargs["max_overflow"] = 10
        _engine = create_engine(url, **kwargs)
    return _engine


def _get_session_factory():
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=_get_engine(), autocommit=False, autoflush=False)
    return _SessionLocal


# Convenience aliases used by the rest of the app
@property  # type: ignore[misc]
def engine():
    return _get_engine()


def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = _get_session_factory()()
    try:
        yield db
    finally:
        db.close()


def create_tables():
    """Create all tables defined via ORM (called on startup)."""
    from backend.models import orm  # noqa: F401 — registers models with Base
    Base.metadata.create_all(bind=_get_engine())


def _reset_engine(new_url: str):
    """Used by tests to swap in a different DB URL (e.g. SQLite)."""
    global _engine, _SessionLocal
    kwargs: dict = {"pool_pre_ping": True}
    if new_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    _engine = create_engine(new_url, **kwargs)
    _SessionLocal = sessionmaker(bind=_engine, autocommit=False, autoflush=False)

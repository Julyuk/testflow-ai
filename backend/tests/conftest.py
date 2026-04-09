"""
Shared test fixtures.

Swaps the database engine to SQLite before any tables are created,
so tests run without a live PostgreSQL instance.
"""

import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

SQLITE_URL = "sqlite:///./test_testflow.db"

# Point the app at SQLite before importing anything that touches the engine
os.environ.setdefault("DATABASE_URL", SQLITE_URL)

from backend.models.database import Base, _reset_engine, get_db  # noqa: E402
from backend.api.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    """Create SQLite tables once per test session, drop them after."""
    _reset_engine(SQLITE_URL)
    from backend.models import orm  # noqa: F401 — register ORM models
    from backend.models.database import _get_engine
    Base.metadata.create_all(bind=_get_engine())
    yield
    Base.metadata.drop_all(bind=_get_engine())


@pytest.fixture()
def db_session(setup_test_db):
    from backend.models.database import _get_engine
    TestingSession = sessionmaker(bind=_get_engine(), autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def client(db_session):
    """FastAPI test client with DB dependency overridden to use the test session."""
    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()

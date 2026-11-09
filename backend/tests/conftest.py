"""Test configuration.

SAFETY: tests run against a SEPARATE MySQL database (default `project_guide_allocation_test`, override with
TEST_DB_NAME). The suite refuses to run unless the database name ends with `_test`, so it can never wipe
the real `project_guide_allocation` database.
"""
import os

TEST_DB = os.environ.get("TEST_DB_NAME", "project_guide_allocation_test")
if not TEST_DB.endswith("_test"):
    raise SystemExit(f"Refusing to run tests: TEST_DB_NAME must end with '_test' (got '{TEST_DB}').")
os.environ["DB_NAME"] = TEST_DB                      # overrides backend/.env before the app is imported
os.environ.setdefault("JWT_SECRET", "test-secret-test-secret-test-secret-123456")
os.environ["LOGIN_MAX_ATTEMPTS"] = "10"

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import inspect, text  # noqa: E402

from app.database import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.security import login_limiter  # noqa: E402
from scripts.seed import seed  # noqa: E402

assert engine.url.database == TEST_DB and TEST_DB.endswith("_test")


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Build the test schema from the real Alembic migrations (this also exercises the migrations)."""
    assert engine.url.database.endswith("_test")
    with engine.begin() as c:
        c.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for t in inspect(c).get_table_names():
            c.execute(text(f"DROP TABLE IF EXISTS `{t}`"))
        c.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(cfg, "head")
    yield


@pytest.fixture(autouse=True)
def _clean():
    assert engine.url.database.endswith("_test")
    with engine.begin() as c:
        c.execute(text("SET FOREIGN_KEY_CHECKS=0"))
        for t in inspect(c).get_table_names():
            if t != "alembic_version":
                c.execute(text(f"TRUNCATE TABLE `{t}`"))
        c.execute(text("SET FOREIGN_KEY_CHECKS=1"))
    with SessionLocal() as db:
        seed(db)
    login_limiter.reset()
    yield


@pytest.fixture
def db():
    with SessionLocal() as s:
        yield s


@pytest.fixture
def client():
    return TestClient(app)

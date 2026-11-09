from datetime import datetime, timezone

from sqlalchemy import DateTime, create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator

from .config import get_settings

_s = get_settings()
# MySQL is the only supported database: there is deliberately no SQLite fallback.
engine = create_engine(
    _s.database_url,
    pool_size=_s.db_pool_size,
    max_overflow=_s.db_max_overflow,
    pool_recycle=_s.db_pool_recycle,
    pool_pre_ping=True,
    # READ COMMITTED + row locks (SELECT ... FOR UPDATE) give predictable behaviour for concurrent admins.
    isolation_level="READ COMMITTED",
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores naive UTC in MySQL, returns timezone-aware UTC datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        return None if value is None else value.replace(tzinfo=timezone.utc)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

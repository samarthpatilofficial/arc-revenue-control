"""SQLAlchemy engine and session lifecycle management."""

from collections.abc import Generator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from arc.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Create the process-wide SQLAlchemy engine on first use."""

    return create_engine(
        get_settings().sqlalchemy_database_url,
        pool_pre_ping=True,
    )


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide configured session factory."""

    return sessionmaker(
        bind=get_engine(),
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )


def get_db_session() -> Generator[Session, None, None]:
    """Yield a request-scoped database session for dependency injection."""

    with get_session_factory()() as session:
        yield session

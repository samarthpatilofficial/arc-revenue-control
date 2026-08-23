"""Shared PostgreSQL integration-test configuration and safety guards."""

from collections.abc import Generator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.orm import Session, sessionmaker

from arc.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORE_TABLES = (
    "case_events",
    "webhook_events",
    "payment_cases",
    "merchant_policies",
)


def _assert_safe_test_database(database_url: URL) -> None:
    database_name = database_url.database
    if not database_name or not database_name.lower().endswith("_test"):
        raise RuntimeError(
            "Destructive database tests require a database name ending in '_test'"
        )


def _resolve_test_database_url() -> URL:
    settings = get_settings()
    configured_test_url = settings.sqlalchemy_test_database_url
    if configured_test_url is not None:
        test_url = make_url(configured_test_url)
    else:
        development_url = make_url(settings.sqlalchemy_database_url)
        development_database = development_url.database
        if development_database is None:
            raise RuntimeError("DATABASE_URL must include a database name")
        if development_database.lower().endswith("_dev"):
            test_database = f"{development_database[:-4]}_test"
        else:
            test_database = f"{development_database}_test"
        test_url = development_url.set(database=test_database)

    _assert_safe_test_database(test_url)
    return test_url


def _alembic_config(database_url: URL) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    rendered_url = database_url.render_as_string(hide_password=False).replace(
        "%", "%%"
    )
    config.set_main_option("sqlalchemy.url", rendered_url)
    return config


@pytest.fixture(scope="session")
def migrated_engine() -> Generator[Engine, None, None]:
    """Rebuild only the guarded test database schema and return its engine."""

    database_url = _resolve_test_database_url()
    _assert_safe_test_database(database_url)
    migration_config = _alembic_config(database_url)

    command.downgrade(migration_config, "base")
    command.upgrade(migration_config, "head")

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as connection:
        connected_database = connection.execute(text("SELECT current_database()"))
        if not connected_database.scalar_one().lower().endswith("_test"):
            raise RuntimeError("Connected database failed the test safety guard")

    yield engine
    engine.dispose()


@pytest.fixture
def db_session(migrated_engine: Engine) -> Generator[Session, None, None]:
    """Return an isolated session after clearing only the guarded test tables."""

    with migrated_engine.begin() as connection:
        table_list = ", ".join(CORE_TABLES)
        connection.execute(
            text(f"TRUNCATE TABLE {table_list} RESTART IDENTITY CASCADE")
        )

    with Session(migrated_engine, expire_on_commit=False) as session:
        yield session
        session.rollback()


@pytest.fixture
def integration_session_factory(
    migrated_engine: Engine,
    db_session: Session,
) -> sessionmaker[Session]:
    """Return a factory after the guarded test tables have been cleared."""

    del db_session
    return sessionmaker(
        bind=migrated_engine,
        class_=Session,
        expire_on_commit=False,
    )

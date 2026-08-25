"""Tests for API liveness."""

import asyncio

from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy.exc import SQLAlchemyError

from arc.config import Settings
from arc.config import get_settings
from arc.db.session import get_db_session


def test_health_endpoint(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://arc:test_only@localhost:5432/arc_test",
    )
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "false")
    get_settings.cache_clear()

    from services.api.main import create_app

    async def get_health_response() -> Response:
        transport = ASGITransport(app=create_app())
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/health")

    response = asyncio.run(get_health_response())

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "arc-api"}

    get_settings.cache_clear()


class _ReadyResult:
    def scalar_one(self) -> int:
        return 1


class _ReadySession:
    def execute(self, _statement: object) -> _ReadyResult:
        return _ReadyResult()


class _UnavailableSession:
    def execute(self, _statement: object) -> _ReadyResult:
        raise SQLAlchemyError("private-database-detail")


def _readiness_response(session: object) -> Response:
    from services.api.main import create_app

    settings = Settings(
        database_url=(
            "postgresql+psycopg://arc:test_only@localhost:5432/arc_test"
        ),
        _env_file=None,
    )
    application = create_app(settings)

    def override_session():
        yield session

    application.dependency_overrides[get_db_session] = override_session

    async def get_response() -> Response:
        transport = ASGITransport(app=application)
        async with AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/ready")

    return asyncio.run(get_response())


def test_readiness_endpoint_reports_database_ready() -> None:
    response = _readiness_response(_ReadySession())

    assert response.status_code == 200
    assert response.json() == {"status": "ready", "service": "arc-api"}


def test_readiness_endpoint_sanitizes_database_failure() -> None:
    response = _readiness_response(_UnavailableSession())

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "DATABASE_NOT_READY",
        "message": "Database is unavailable",
    }
    assert "private-database-detail" not in response.text

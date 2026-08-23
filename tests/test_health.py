"""Tests for API liveness."""

import asyncio

from httpx import ASGITransport, AsyncClient, Response

from arc.config import get_settings


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

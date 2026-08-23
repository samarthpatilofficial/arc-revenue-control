"""Tests for typed application configuration."""

from arc.config import get_settings


def test_settings_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://arc:test_only@localhost:5432/arc_test",
    )
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "true")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.environment == "test"
    assert settings.debug is True
    assert settings.sqlalchemy_database_url.startswith("postgresql+psycopg://")

    get_settings.cache_clear()

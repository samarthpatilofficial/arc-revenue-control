"""Tests for typed application configuration."""

from arc.config import get_settings


def test_settings_load_from_environment(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://arc:test_only@localhost:5432/arc_test",
    )
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://arc:test_only@localhost:5432/arc_test",
    )
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("DEBUG", "true")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")
    monkeypatch.setenv(
        "RAZORPAY_WEBHOOK_PREVIOUS_SECRET",
        "test_previous_webhook_secret",
    )
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.environment == "test"
    assert settings.debug is True
    assert settings.sqlalchemy_database_url.startswith("postgresql+psycopg://")
    assert settings.sqlalchemy_test_database_url is not None
    assert settings.sqlalchemy_test_database_url.endswith("/arc_test")
    assert settings.razorpay_webhook_secret is not None
    assert (
        settings.razorpay_webhook_secret.get_secret_value()
        == "test_webhook_secret"
    )
    assert settings.razorpay_webhook_previous_secret is not None
    assert "test_webhook_secret" not in repr(settings)
    assert "test_previous_webhook_secret" not in repr(settings)

    get_settings.cache_clear()

"""Tests for typed application configuration."""

import pytest
from pydantic import ValidationError

from arc.config import Settings, get_settings


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
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_config_only")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "config_only_secret")
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "test_webhook_secret")
    monkeypatch.setenv("OPENAI_API_KEY", "config_only_openai_secret")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.6-luna")
    monkeypatch.setenv("ARC_DEMO_MODE", "true")
    monkeypatch.setenv(
        "CORS_ALLOWED_ORIGINS",
        '["http://localhost:5173", "https://demo.example.test/"]',
    )
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
    assert settings.razorpay_key_id is not None
    assert settings.razorpay_key_secret is not None
    assert settings.openai_api_key is not None
    assert settings.openai_model == "gpt-5.6-luna"
    assert settings.demo_mode is True
    assert settings.cors_allowed_origins == [
        "http://localhost:5173",
        "https://demo.example.test",
    ]
    assert (
        settings.razorpay_webhook_secret.get_secret_value()
        == "test_webhook_secret"
    )
    assert settings.razorpay_webhook_previous_secret is not None
    assert "test_webhook_secret" not in repr(settings)
    assert "test_previous_webhook_secret" not in repr(settings)
    assert "rzp_test_config_only" not in repr(settings)
    assert "config_only_secret" not in repr(settings)
    assert "config_only_openai_secret" not in repr(settings)

    get_settings.cache_clear()


def test_openai_key_is_optional_at_startup() -> None:
    settings = Settings(
        database_url=(
            "postgresql+psycopg://arc:test_only@localhost:5432/arc_test"
        ),
        openai_api_key=None,
        _env_file=None,
    )

    assert settings.openai_api_key is None
    assert settings.openai_model == "gpt-5.6-luna"
    assert settings.demo_mode is False
    assert settings.cors_allowed_origins == []


def test_cors_wildcard_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(
            database_url=(
                "postgresql+psycopg://arc:test_only@localhost:5432/arc_test"
            ),
            cors_allowed_origins=["*"],
            _env_file=None,
        )

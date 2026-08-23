"""Application configuration loaded from environment variables."""

from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings for the ARC backend."""

    database_url: PostgresDsn
    test_database_url: PostgresDsn | None = None
    razorpay_key_id: SecretStr | None = None
    razorpay_key_secret: SecretStr | None = None
    razorpay_api_base_url: AnyHttpUrl = "https://api.razorpay.com"
    razorpay_webhook_secret: SecretStr | None = None
    razorpay_webhook_previous_secret: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    openai_model: str = "gpt-5.6-luna"
    openai_api_base_url: AnyHttpUrl = "https://api.openai.com/v1"
    environment: str = "development"
    debug: bool = False
    demo_mode: bool = Field(
        default=False,
        validation_alias="ARC_DEMO_MODE",
    )
    cors_allowed_origins: list[str] = Field(default_factory=list)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("cors_allowed_origins")
    @classmethod
    def validate_cors_allowed_origins(cls, values: list[str]) -> list[str]:
        """Accept only explicit HTTP(S) origins and reject wildcard access."""

        normalized: list[str] = []
        for value in values:
            candidate = value.strip()
            parsed = urlsplit(candidate)
            if (
                candidate == "*"
                or parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError("CORS origins must be explicit HTTP(S) origins")
            origin = candidate.rstrip("/")
            if origin not in normalized:
                normalized.append(origin)
        return normalized

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return the validated database URL in SQLAlchemy's string form."""

        return str(self.database_url)

    @property
    def sqlalchemy_test_database_url(self) -> str | None:
        """Return the optional test database URL in SQLAlchemy's string form."""

        if self.test_database_url is None:
            return None
        return str(self.test_database_url)


@lru_cache
def get_settings() -> Settings:
    """Return one validated settings instance per process."""

    return Settings()

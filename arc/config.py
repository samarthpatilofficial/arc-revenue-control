"""Application configuration loaded from environment variables."""

from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed runtime settings for the ARC backend."""

    database_url: PostgresDsn
    test_database_url: PostgresDsn | None = None
    environment: str = "development"
    debug: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

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

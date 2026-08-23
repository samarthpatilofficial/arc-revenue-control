"""Request-scoped API dependencies."""

from fastapi import Request

from arc.config import Settings


def get_request_settings(request: Request) -> Settings:
    """Return the settings instance used to construct this application."""

    return request.app.state.settings

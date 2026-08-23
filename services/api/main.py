"""FastAPI application factory and ASGI entry point."""

from fastapi import FastAPI

from arc.config import Settings, get_settings
from services.api.routes import api_router


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and configure the ARC API application."""

    app_settings = settings or get_settings()
    application = FastAPI(
        title="ARC API",
        description="Backend service for ARC Autonomous Revenue Control.",
        version="0.1.0",
        debug=app_settings.debug,
    )
    application.include_router(api_router)
    return application


app = create_app()

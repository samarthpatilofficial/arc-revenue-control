"""FastAPI application factory and ASGI entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    application.state.settings = app_settings
    if app_settings.cors_allowed_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=app_settings.cors_allowed_origins,
            allow_credentials=True,
            allow_methods=["GET"],
            allow_headers=["Accept", "Content-Type"],
        )
    application.include_router(api_router)
    return application


app = create_app()

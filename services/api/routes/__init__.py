"""Route registration for the ARC API."""

from fastapi import APIRouter

from services.api.routes.health import router as health_router
from services.api.routes.razorpay_webhooks import router as razorpay_webhook_router
from services.api.routes.read_api import router as read_api_router


def build_api_router(*, public_demo_mode: bool) -> APIRouter:
    """Compose routes at startup so public demo ingress is absent."""

    api_router = APIRouter()
    api_router.include_router(health_router)
    api_router.include_router(read_api_router)
    if not public_demo_mode:
        api_router.include_router(razorpay_webhook_router)
    return api_router


__all__ = ["build_api_router"]

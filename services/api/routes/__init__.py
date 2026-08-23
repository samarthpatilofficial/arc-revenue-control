"""Route registration for the ARC API."""

from fastapi import APIRouter

from services.api.routes.health import router as health_router
from services.api.routes.razorpay_webhooks import router as razorpay_webhook_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(razorpay_webhook_router)

__all__ = ["api_router"]

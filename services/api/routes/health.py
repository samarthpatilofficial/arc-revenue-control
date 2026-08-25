"""System liveness and database readiness routes."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arc.db.session import get_db_session

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    """Liveness response for the API service."""

    status: str
    service: str


class ReadinessResponse(BaseModel):
    """Sanitized readiness response for deployment probes."""

    status: str
    service: str


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Report that the API process is available."""

    return HealthResponse(status="ok", service="arc-api")


@router.get("/ready", response_model=ReadinessResponse)
def ready(
    session: Annotated[Session, Depends(get_db_session)],
) -> ReadinessResponse:
    """Verify minimal database access without exposing connection details."""

    try:
        session.execute(text("SELECT 1")).scalar_one()
    except (SQLAlchemyError, OSError):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "DATABASE_NOT_READY",
                "message": "Database is unavailable",
            },
        ) from None
    return ReadinessResponse(status="ready", service="arc-api")

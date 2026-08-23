"""Secure Razorpay webhook ingress routes."""

import json
from typing import Annotated, Any, Literal, NoReturn

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from arc.config import Settings
from arc.db.session import get_db_session
from arc.domain.enums import EventProcessingStatus
from arc.integrations.razorpay import (
    InvalidWebhookPayload,
    hash_raw_body,
    normalize_webhook_payload,
    verify_webhook_signature_with_rotation,
)
from arc.persistence import EventPersistenceError, record_event_once
from services.api.dependencies import get_request_settings

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


class WebhookIngestionResponse(BaseModel):
    """Minimal acknowledgement that never echoes payment payload data."""

    status: Literal["accepted"]
    duplicate: bool
    event_id: str


def _reject_nonstandard_json(value: str) -> NoReturn:
    raise ValueError(f"Non-standard JSON constant is not allowed: {value}")


@router.post(
    "/razorpay",
    response_model=WebhookIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_razorpay_webhook(
    request: Request,
    settings: Annotated[Settings, Depends(get_request_settings)],
    session: Annotated[Session, Depends(get_db_session)],
) -> WebhookIngestionResponse:
    """Verify, normalize, and durably record one Razorpay webhook event."""

    raw_body = await request.body()
    received_signature = request.headers.get("X-Razorpay-Signature")
    if not received_signature:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing webhook signature",
        )

    configured_secret = settings.razorpay_webhook_secret
    if configured_secret is None or not configured_secret.get_secret_value():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook ingestion is not configured",
        )

    previous_secret = settings.razorpay_webhook_previous_secret
    signature_valid = verify_webhook_signature_with_rotation(
        raw_body,
        received_signature,
        configured_secret.get_secret_value(),
        previous_secret.get_secret_value() if previous_secret else None,
    )
    if not signature_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )

    try:
        parsed_payload: Any = json.loads(
            raw_body,
            parse_constant=_reject_nonstandard_json,
        )
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook JSON",
        ) from None

    event_id = request.headers.get("x-razorpay-event-id")
    if not event_id or len(event_id) > 128:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing or invalid Razorpay event id",
        )

    try:
        normalized = normalize_webhook_payload(parsed_payload)
    except InvalidWebhookPayload as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(error),
        ) from None

    raw_body_digest = hash_raw_body(raw_body)
    processing_status = (
        EventProcessingStatus.RECEIVED
        if normalized.supported
        else EventProcessingStatus.UNSUPPORTED
    )

    try:
        result = record_event_once(
            session,
            razorpay_event_id=event_id,
            event_type=normalized.event_type,
            account_id=normalized.account_id,
            payment_id=normalized.payment_id,
            subscription_id=normalized.subscription_id,
            customer_id=normalized.customer_id,
            raw_payload=normalized.raw_payload,
            raw_body_sha256=raw_body_digest,
            signature_verified=True,
            processing_status=processing_status,
        )
    except (EventPersistenceError, SQLAlchemyError):
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook persistence unavailable",
        ) from None

    if result.integrity_mismatch:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Event id already exists with different request content",
        )

    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook persistence unavailable",
        ) from None

    return WebhookIngestionResponse(
        status="accepted",
        duplicate=result.duplicate,
        event_id=event_id,
    )

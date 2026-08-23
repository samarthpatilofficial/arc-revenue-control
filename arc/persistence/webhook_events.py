"""Race-safe persistence for the immutable webhook event ledger."""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from arc.domain.enums import EventProcessingStatus
from arc.domain.models import WebhookEvent


@dataclass(frozen=True, slots=True)
class RecordEventResult:
    """Outcome of recording one external event idempotently."""

    inserted: bool
    duplicate: bool
    integrity_mismatch: bool
    event: WebhookEvent


class EventPersistenceError(RuntimeError):
    """Raised when an event insert outcome cannot be resolved deterministically."""


def hash_payload(raw_payload: Mapping[str, Any]) -> str:
    """Return a SHA-256 hash of the payload's canonical JSON representation."""

    canonical_payload = json.dumps(
        raw_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical_payload).hexdigest()


def record_event_once(
    session: Session,
    *,
    razorpay_event_id: str,
    event_type: str,
    raw_payload: Mapping[str, Any],
    signature_verified: bool,
    raw_body_sha256: str,
    processing_status: EventProcessingStatus = EventProcessingStatus.RECEIVED,
    account_id: str | None = None,
    payment_id: str | None = None,
    subscription_id: str | None = None,
    customer_id: str | None = None,
    received_at: datetime | None = None,
) -> RecordEventResult:
    """Insert an event once using PostgreSQL's unique-conflict handling.

    The operation never performs a check-then-insert sequence. PostgreSQL's
    UNIQUE constraint is the final idempotency authority, and ON CONFLICT keeps
    the caller's transaction usable when a duplicate is received.
    """

    payload = dict(raw_payload)
    values: dict[str, Any] = {
        "id": uuid4(),
        "razorpay_event_id": razorpay_event_id,
        "event_type": event_type,
        "account_id": account_id,
        "payment_id": payment_id,
        "subscription_id": subscription_id,
        "customer_id": customer_id,
        "raw_payload": payload,
        "payload_hash": hash_payload(payload),
        "raw_body_sha256": raw_body_sha256,
        "signature_verified": signature_verified,
        "processing_status": processing_status,
    }
    if received_at is not None:
        values["received_at"] = received_at

    statement = (
        insert(WebhookEvent)
        .values(**values)
        .on_conflict_do_nothing(
            constraint="uq_webhook_events_razorpay_event_id"
        )
        .returning(WebhookEvent.id)
    )
    inserted_id = session.execute(statement).scalar_one_or_none()

    if inserted_id is not None:
        event_record = session.scalar(
            select(WebhookEvent).where(WebhookEvent.id == inserted_id)
        )
        if event_record is None:
            raise EventPersistenceError(
                "Inserted webhook event could not be reloaded"
            )
        return RecordEventResult(
            inserted=True,
            duplicate=False,
            integrity_mismatch=False,
            event=event_record,
        )

    event_record = session.scalar(
        select(WebhookEvent).where(
            WebhookEvent.razorpay_event_id == razorpay_event_id
        )
    )
    if event_record is None:
        raise EventPersistenceError("Duplicate webhook event could not be loaded")

    # A null stored digest identifies a legacy row whose exact request bytes
    # cannot be proven equal, so webhook ingestion fails closed as an anomaly.
    integrity_mismatch = event_record.raw_body_sha256 != raw_body_sha256

    return RecordEventResult(
        inserted=False,
        duplicate=True,
        integrity_mismatch=integrity_mismatch,
        event=event_record,
    )

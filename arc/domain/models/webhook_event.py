"""Immutable external webhook event ledger model."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SqlEnum,
    Index,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
    inspect,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Mapped, Mapper, mapped_column

from arc.db.base import Base
from arc.domain.enums import EventProcessingStatus

event_processing_status_type = SqlEnum(
    EventProcessingStatus,
    name="event_processing_status",
    native_enum=False,
    create_constraint=False,
    validate_strings=True,
    values_callable=lambda enum_type: [member.value for member in enum_type],
    length=32,
)


class WebhookEvent(Base):
    """Accepted external event with immutable payload and mutable processing metadata."""

    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "razorpay_event_id",
            name="uq_webhook_events_razorpay_event_id",
        ),
        CheckConstraint(
            "payload_hash ~ '^[0-9a-f]{64}$'",
            name="payload_hash_sha256_hex",
        ),
        CheckConstraint(
            "processing_status IN "
            "('RECEIVED', 'PROCESSING', 'PROCESSED', 'FAILED', 'UNSUPPORTED')",
            name="event_processing_status",
        ),
        Index("ix_webhook_events_event_type", "event_type"),
        Index("ix_webhook_events_received_at", "received_at"),
        Index("ix_webhook_events_payment_id", "payment_id"),
        Index("ix_webhook_events_subscription_id", "subscription_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    razorpay_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    account_id: Mapped[str | None] = mapped_column(String(100))
    payment_id: Mapped[str | None] = mapped_column(String(100))
    subscription_id: Mapped[str | None] = mapped_column(String(100))
    customer_id: Mapped[str | None] = mapped_column(String(100))
    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    signature_verified: Mapped[bool] = mapped_column(Boolean, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processing_status: Mapped[EventProcessingStatus] = mapped_column(
        event_processing_status_type,
        nullable=False,
        default=EventProcessingStatus.RECEIVED,
        server_default=EventProcessingStatus.RECEIVED.value,
    )
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processing_error: Mapped[str | None] = mapped_column(Text)


_IMMUTABLE_EVENT_FIELDS = (
    "id",
    "razorpay_event_id",
    "event_type",
    "account_id",
    "payment_id",
    "subscription_id",
    "customer_id",
    "raw_payload",
    "payload_hash",
    "signature_verified",
    "received_at",
)


@event.listens_for(WebhookEvent, "before_update")
def _prevent_event_payload_update(
    _mapper: Mapper[WebhookEvent],
    _connection: Connection,
    target: WebhookEvent,
) -> None:
    changed_fields = [
        field
        for field in _IMMUTABLE_EVENT_FIELDS
        if inspect(target).attrs[field].history.has_changes()
    ]
    if changed_fields:
        names = ", ".join(changed_fields)
        raise ValueError(f"Webhook event ledger fields are immutable: {names}")


@event.listens_for(WebhookEvent, "before_delete")
def _prevent_event_delete(
    _mapper: Mapper[WebhookEvent],
    _connection: Connection,
    _target: WebhookEvent,
) -> None:
    raise ValueError("Webhook event ledger records cannot be deleted")

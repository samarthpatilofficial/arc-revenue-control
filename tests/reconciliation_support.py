"""Shared deterministic fakes and persistence helpers for reconciliation tests."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from arc.assessment import CaseAssessmentService
from arc.domain.enums import EventProcessingStatus
from arc.domain.models import CaseEvent, PaymentCase, WebhookEvent
from arc.integrations.razorpay import PaymentSnapshot, SubscriptionSnapshot
from arc.integrations.razorpay.webhook_security import hash_raw_body
from arc.persistence import record_event_once
from arc.reconciliation import WebhookEventProcessor

SessionFactory = sessionmaker[Session]


class StubRazorpayClient:
    """In-memory read client that never performs network I/O."""

    def __init__(self) -> None:
        self.payments: dict[str, PaymentSnapshot | Exception] = {}
        self.subscriptions: dict[str, SubscriptionSnapshot | Exception] = {}
        self.calls: list[tuple[str, str]] = []
        self.on_fetch: Callable[[], None] | None = None

    def fetch_payment(self, payment_id: str) -> PaymentSnapshot:
        self.calls.append(("payment", payment_id))
        if self.on_fetch is not None:
            self.on_fetch()
        result = self.payments[payment_id]
        if isinstance(result, Exception):
            raise result
        return result

    def fetch_subscription(self, subscription_id: str) -> SubscriptionSnapshot:
        self.calls.append(("subscription", subscription_id))
        if self.on_fetch is not None:
            self.on_fetch()
        result = self.subscriptions[subscription_id]
        if isinstance(result, Exception):
            raise result
        return result


def payment_snapshot(
    *,
    payment_id: str = "pay_test",
    status: str = "failed",
    amount: int = 18_501,
    currency: str = "INR",
    customer_id: str | None = "cust_authoritative",
    subscription_id: str | None = None,
    method: str | None = "card",
    error_code: str | None = "BAD_REQUEST_ERROR",
    error_description: str | None = "Synthetic test failure",
    error_source: str | None = "customer",
    error_step: str | None = "payment_authentication",
    error_reason: str | None = "incorrect_otp",
) -> PaymentSnapshot:
    return PaymentSnapshot.model_validate(
        {
            "id": payment_id,
            "status": status,
            "amount": amount,
            "currency": currency,
            "customer_id": customer_id,
            "subscription_id": subscription_id,
            "order_id": "order_test",
            "method": method,
            "error_code": error_code if status == "failed" else None,
            "error_description": (
                error_description if status == "failed" else None
            ),
            "error_source": error_source if status == "failed" else None,
            "error_step": error_step if status == "failed" else None,
            "error_reason": error_reason if status == "failed" else None,
            "created_at": 1_725_000_000,
        }
    )


def subscription_snapshot(
    *,
    subscription_id: str = "sub_test",
    status: str = "pending",
    customer_id: str | None = "cust_authoritative",
) -> SubscriptionSnapshot:
    return SubscriptionSnapshot.model_validate(
        {
            "id": subscription_id,
            "status": status,
            "customer_id": customer_id,
            "current_start": 1_725_000_000,
            "current_end": 1_727_592_000,
            "charge_at": 1_725_086_400,
            "paid_count": 2,
            "remaining_count": 4,
            "customer_notify": True,
            "payment_method": "card",
            "created_at": 1_720_000_000,
        }
    )


def store_event(
    session_factory: SessionFactory,
    *,
    event_type: str,
    payment_id: str | None = None,
    subscription_id: str | None = None,
    event_id: str | None = None,
    customer_id: str | None = "cust_webhook",
    account_id: str | None = "acc_test",
    processing_status: EventProcessingStatus = EventProcessingStatus.RECEIVED,
    processing_started_at: datetime | None = None,
    processing_attempt_count: int = 0,
    processing_error: str | None = None,
) -> UUID:
    razorpay_event_id = event_id or f"evt_{uuid4().hex}"
    raw_payload: dict[str, Any] = {
        "event": event_type,
        "payload": {},
    }
    raw_body = json.dumps(raw_payload, separators=(",", ":")).encode("utf-8")
    with session_factory() as session:
        result = record_event_once(
            session,
            razorpay_event_id=razorpay_event_id,
            event_type=event_type,
            account_id=account_id,
            payment_id=payment_id,
            subscription_id=subscription_id,
            customer_id=customer_id,
            raw_payload=raw_payload,
            raw_body_sha256=hash_raw_body(raw_body),
            signature_verified=True,
            processing_status=processing_status,
        )
        result.event.processing_started_at = processing_started_at
        result.event.processing_attempt_count = processing_attempt_count
        result.event.processing_error = processing_error
        session.commit()
        return result.event.id


def processor(
    session_factory: SessionFactory,
    client: StubRazorpayClient,
    *,
    clock: Callable[[], datetime] | None = None,
) -> WebhookEventProcessor:
    if clock is None:
        return WebhookEventProcessor(
            session_factory=session_factory,
            razorpay_client=client,
        )
    return WebhookEventProcessor(
        session_factory=session_factory,
        razorpay_client=client,
        clock=clock,
    )


def assessor(
    session_factory: SessionFactory,
    *,
    clock: Callable[[], datetime],
) -> CaseAssessmentService:
    return CaseAssessmentService(
        session_factory=session_factory,
        clock=clock,
    )


def load_event(session_factory: SessionFactory, event_id: UUID) -> WebhookEvent:
    with session_factory() as session:
        event = session.get(WebhookEvent, event_id)
        assert event is not None
        session.expunge(event)
        return event


def load_cases(session_factory: SessionFactory) -> list[PaymentCase]:
    with session_factory() as session:
        cases = list(session.scalars(select(PaymentCase).order_by(PaymentCase.created_at)))
        for payment_case in cases:
            session.expunge(payment_case)
        return cases


def load_case_events(
    session_factory: SessionFactory,
    case_id: UUID,
) -> list[CaseEvent]:
    with session_factory() as session:
        case_events = list(
            session.scalars(
                select(CaseEvent)
                .where(CaseEvent.case_id == case_id)
                .order_by(CaseEvent.created_at, CaseEvent.id)
            )
        )
        for case_event in case_events:
            session.expunge(case_event)
        return case_events

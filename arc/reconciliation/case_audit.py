"""Shared case initialization, transition, and reconciliation audit helpers."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from arc.domain.enums import CaseState
from arc.domain.models import CaseEvent, PaymentCase, WebhookEvent
from arc.reconciliation.state_machine import can_transition, transition_case

RECONCILIATION_SOURCE = "RAZORPAY_RECONCILIATION"
UNKNOWN_MERCHANT_ID = "unknown"


def initialize_case_audit(
    session: Session,
    payment_case: PaymentCase,
    event: WebhookEvent,
    external_status: str,
    reconciled_at: datetime,
    *,
    created: bool,
) -> None:
    """Append the initial detection fact only for a newly inserted case."""

    if not created:
        return
    session.add(
        CaseEvent(
            case_id=payment_case.id,
            event_type="CASE_DETECTED",
            source=RECONCILIATION_SOURCE,
            event_data={
                "source_webhook_event_id": event.razorpay_event_id,
                "previous_state": None,
                "new_state": CaseState.DETECTED.value,
                "external_status": external_status,
                "reason_code": "CASE_DETECTED",
                "reconciled_at": reconciled_at.isoformat(),
            },
        )
    )


def move_detected_case_to_reconciling(
    session: Session,
    payment_case: PaymentCase,
    event: WebhookEvent,
    external_status: str,
    reconciled_at: datetime,
) -> None:
    """Move only an eligible early case into active reconciliation."""

    if not can_transition(payment_case.current_state, CaseState.RECONCILING):
        return
    transition_case(
        session,
        payment_case,
        CaseState.RECONCILING,
        reason_code="AUTHORITATIVE_RECONCILIATION_STARTED",
        source=RECONCILIATION_SOURCE,
        metadata={
            "source_webhook_event_id": event.razorpay_event_id,
            "external_status": external_status,
            "reconciled_at": reconciled_at.isoformat(),
        },
    )


def transition_if_allowed(
    session: Session,
    payment_case: PaymentCase,
    target_state: CaseState,
    *,
    reason_code: str,
    event: WebhookEvent,
    external_status: str,
    reconciled_at: datetime,
) -> None:
    """Apply an authoritative transition without overriding terminal guards."""

    if not can_transition(payment_case.current_state, target_state):
        return
    transition_case(
        session,
        payment_case,
        target_state,
        reason_code=reason_code,
        source=RECONCILIATION_SOURCE,
        metadata={
            "source_webhook_event_id": event.razorpay_event_id,
            "external_status": external_status,
            "reconciled_at": reconciled_at.isoformat(),
        },
    )


def append_reconciliation_audit(
    session: Session,
    payment_case: PaymentCase,
    event: WebhookEvent,
    *,
    previous_state: CaseState,
    reason_code: str,
    external_status: str,
    reconciled_at: datetime,
) -> None:
    """Append one sanitized fact about authoritative external truth."""

    event_data: dict[str, Any] = {
        "source_webhook_event_id": event.razorpay_event_id,
        "previous_state": previous_state.value,
        "new_state": payment_case.current_state.value,
        "external_status": external_status,
        "reason_code": reason_code,
        "reconciled_at": reconciled_at.isoformat(),
    }
    session.add(
        CaseEvent(
            case_id=payment_case.id,
            event_type=reason_code,
            source=RECONCILIATION_SOURCE,
            event_data=event_data,
        )
    )

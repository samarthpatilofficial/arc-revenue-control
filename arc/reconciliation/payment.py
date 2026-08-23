"""Authoritative payment reconciliation rules."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from arc.domain.enums import CaseState
from arc.domain.models import WebhookEvent
from arc.integrations.razorpay import (
    RECOGNIZED_PAYMENT_STATUSES,
    PaymentSnapshot,
)
from arc.persistence import get_or_create_case, lock_case_by_identity
from arc.reconciliation.case_audit import (
    UNKNOWN_MERCHANT_ID,
    append_reconciliation_audit,
    initialize_case_audit,
    move_detected_case_to_reconciling,
    transition_if_allowed,
)
from arc.reconciliation.errors import WebhookProcessingError


def reconcile_payment(
    session: Session,
    event: WebhookEvent,
    snapshot: PaymentSnapshot,
) -> tuple[UUID | None, str]:
    """Apply current payment truth to one existing or newly detected case."""

    if event.payment_id is None or snapshot.id != event.payment_id:
        raise WebhookProcessingError(
            "Razorpay payment response did not match the requested entity"
        )

    payment_case = lock_case_by_identity(
        session,
        identity_kind="payment",
        external_id=event.payment_id,
    )
    if event.event_type == "payment.captured" and payment_case is None:
        if snapshot.status == "captured":
            return None, "CAPTURE_CONFIRMED_WITHOUT_RECOVERY_CASE"
        return None, "PAYMENT_CAPTURE_SIGNAL_NOT_CONFIRMED"

    created = False
    if payment_case is None:
        result = get_or_create_case(
            session,
            identity_kind="payment",
            external_id=event.payment_id,
            merchant_id=event.account_id or UNKNOWN_MERCHANT_ID,
            customer_id=snapshot.customer_id or event.customer_id,
        )
        payment_case = result.payment_case
        created = result.created

    reconciled_at = datetime.now(UTC)
    initialize_case_audit(
        session,
        payment_case,
        event,
        snapshot.status,
        reconciled_at,
        created=created,
    )
    move_detected_case_to_reconciling(
        session,
        payment_case,
        event,
        snapshot.status,
        reconciled_at,
    )

    payment_case.payment_id = snapshot.id
    payment_case.subscription_id = (
        snapshot.subscription_id
        or event.subscription_id
        or payment_case.subscription_id
    )
    payment_case.customer_id = snapshot.customer_id or payment_case.customer_id
    payment_case.amount = snapshot.amount
    payment_case.currency = snapshot.currency
    payment_case.razorpay_payment_status = snapshot.status
    payment_case.razorpay_payment_method = snapshot.method
    payment_case.error_code = snapshot.error_code
    payment_case.error_description = snapshot.error_description
    payment_case.error_source = snapshot.error_source
    payment_case.error_step = snapshot.error_step
    payment_case.error_reason = snapshot.error_reason
    payment_case.last_reconciled_at = reconciled_at

    previous_state = payment_case.current_state
    if snapshot.status == "captured":
        transition_if_allowed(
            session,
            payment_case,
            CaseState.RECOVERED,
            reason_code="RECONCILIATION_FOUND_ALREADY_CAPTURED",
            event=event,
            external_status=snapshot.status,
            reconciled_at=reconciled_at,
        )
        if payment_case.current_state is CaseState.RECOVERED:
            payment_case.resolved_at = payment_case.resolved_at or reconciled_at
        reason_code = "RECONCILIATION_FOUND_ALREADY_CAPTURED"
    elif snapshot.status == "refunded":
        transition_if_allowed(
            session,
            payment_case,
            CaseState.EXHAUSTED,
            reason_code="PAYMENT_REFUNDED",
            event=event,
            external_status=snapshot.status,
            reconciled_at=reconciled_at,
        )
        if payment_case.current_state is CaseState.EXHAUSTED:
            payment_case.resolved_at = payment_case.resolved_at or reconciled_at
        reason_code = "PAYMENT_REFUNDED"
    elif snapshot.status == "failed":
        reason_code = (
            "RECONCILIATION_CONFIRMED_FAILURE"
            if event.event_type == "payment.failed"
            else "PAYMENT_CAPTURE_SIGNAL_NOT_CONFIRMED"
        )
    elif snapshot.status in {"created", "authorized"}:
        reason_code = "PAYMENT_STATE_NOT_RECOVERY_READY"
    elif snapshot.status not in RECOGNIZED_PAYMENT_STATUSES:
        reason_code = "PAYMENT_STATUS_UNRECOGNIZED"
    else:
        reason_code = "PAYMENT_STATE_NOT_RECOVERY_READY"

    append_reconciliation_audit(
        session,
        payment_case,
        event,
        previous_state=previous_state,
        reason_code=reason_code,
        external_status=snapshot.status,
        reconciled_at=reconciled_at,
    )
    return payment_case.id, reason_code

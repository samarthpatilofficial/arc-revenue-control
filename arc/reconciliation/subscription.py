"""Authoritative subscription reconciliation rules."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from arc.domain.enums import CaseState
from arc.domain.models import WebhookEvent
from arc.integrations.razorpay import (
    RECOGNIZED_SUBSCRIPTION_STATUSES,
    SubscriptionSnapshot,
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


def reconcile_subscription(
    session: Session,
    event: WebhookEvent,
    snapshot: SubscriptionSnapshot,
) -> tuple[UUID | None, str]:
    """Apply current subscription truth without competing with platform retries."""

    if event.subscription_id is None or snapshot.id != event.subscription_id:
        raise WebhookProcessingError(
            "Razorpay subscription response did not match the requested entity"
        )

    payment_case = lock_case_by_identity(
        session,
        identity_kind="subscription",
        external_id=event.subscription_id,
    )
    should_create = snapshot.status in {"pending", "halted"}
    if payment_case is None and not should_create:
        if snapshot.status == "active":
            return None, "SUBSCRIPTION_ACTIVE_NO_RECOVERY_REQUIRED"
        if snapshot.status not in RECOGNIZED_SUBSCRIPTION_STATUSES:
            return None, "SUBSCRIPTION_STATUS_UNRECOGNIZED"
        return None, "SUBSCRIPTION_STATE_NOT_RECOVERY_READY"

    created = False
    if payment_case is None:
        result = get_or_create_case(
            session,
            identity_kind="subscription",
            external_id=event.subscription_id,
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
    if snapshot.status in {"pending", "halted"}:
        move_detected_case_to_reconciling(
            session,
            payment_case,
            event,
            snapshot.status,
            reconciled_at,
        )

    payment_case.subscription_id = snapshot.id
    payment_case.customer_id = snapshot.customer_id or payment_case.customer_id
    payment_case.razorpay_subscription_status = snapshot.status
    payment_case.last_reconciled_at = reconciled_at

    previous_state = payment_case.current_state
    if snapshot.status == "pending":
        reason_code = "PLATFORM_RETRY_ACTIVE"
    elif snapshot.status == "halted":
        reason_code = "SUBSCRIPTION_RETRIES_EXHAUSTED"
    elif snapshot.status == "active":
        transition_if_allowed(
            session,
            payment_case,
            CaseState.RECOVERED,
            reason_code="SUBSCRIPTION_ACTIVE_NO_RECOVERY_REQUIRED",
            event=event,
            external_status=snapshot.status,
            reconciled_at=reconciled_at,
        )
        if payment_case.current_state is CaseState.RECOVERED:
            payment_case.resolved_at = payment_case.resolved_at or reconciled_at
        reason_code = "SUBSCRIPTION_ACTIVE_NO_RECOVERY_REQUIRED"
    elif snapshot.status in {"cancelled", "completed", "expired"}:
        transition_if_allowed(
            session,
            payment_case,
            CaseState.EXHAUSTED,
            reason_code="SUBSCRIPTION_TERMINAL_WITHOUT_RECOVERY",
            event=event,
            external_status=snapshot.status,
            reconciled_at=reconciled_at,
        )
        if payment_case.current_state is CaseState.EXHAUSTED:
            payment_case.resolved_at = payment_case.resolved_at or reconciled_at
        reason_code = "SUBSCRIPTION_TERMINAL_WITHOUT_RECOVERY"
    elif snapshot.status not in RECOGNIZED_SUBSCRIPTION_STATUSES:
        reason_code = "SUBSCRIPTION_STATUS_UNRECOGNIZED"
    else:
        reason_code = "SUBSCRIPTION_STATE_NOT_RECOVERY_READY"

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

"""Bounded merchant authorization audit events without raw policy JSON."""

from sqlalchemy.orm import Session

from arc.domain.enums import CaseState, PolicyDecisionResult, RecoveryAction
from arc.domain.models import CaseEvent, PaymentCase, PolicyDecision

POLICY_AUDIT_SOURCE = "MERCHANT_POLICY"


def append_policy_audit(
    session: Session,
    payment_case: PaymentCase,
    decision: PolicyDecision,
    *,
    action: RecoveryAction,
    previous_state: CaseState,
    reevaluated: bool,
) -> None:
    """Append one bounded result-specific policy audit entry."""

    event_type = (
        "POLICY_REEVALUATED"
        if reevaluated
        else {
            PolicyDecisionResult.AUTHORIZED: "POLICY_AUTHORIZED",
            PolicyDecisionResult.REQUIRES_APPROVAL: (
                "POLICY_REQUIRES_APPROVAL"
            ),
            PolicyDecisionResult.BLOCKED: "POLICY_BLOCKED",
        }[decision.result]
    )
    session.add(
        CaseEvent(
            case_id=payment_case.id,
            event_type=event_type,
            source=POLICY_AUDIT_SOURCE,
            event_data={
                "policy_decision_id": str(decision.id),
                "strategy_proposal_id": str(decision.strategy_proposal_id),
                "action": action.value,
                "result": decision.result.value,
                "reason_code": decision.reason_code,
                "policy_fingerprint": decision.policy_fingerprint,
                "authorization_input_fingerprint": (
                    decision.authorization_input_fingerprint
                ),
                "observed_amount_minor": decision.observed_amount_minor,
                "approval_threshold_minor": (
                    decision.approval_threshold_minor
                ),
                "high_value_threshold_minor": (
                    decision.high_value_threshold_minor
                ),
                "observed_high_value": decision.observed_high_value,
                "observed_attempt_count": decision.observed_attempt_count,
                "observed_contact_attempt_count": (
                    decision.observed_contact_attempt_count
                ),
                "recovery_window_ends_at": (
                    decision.recovery_window_ends_at.isoformat()
                    if decision.recovery_window_ends_at is not None
                    else None
                ),
                "previous_state": previous_state.value,
                "new_state": payment_case.current_state.value,
            },
        )
    )

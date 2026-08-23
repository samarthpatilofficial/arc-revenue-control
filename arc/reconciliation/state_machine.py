"""Explicit, audited lifecycle transitions for ARC recovery cases."""

from dataclasses import dataclass
from typing import Any, Mapping

from sqlalchemy.orm import Session

from arc.domain.enums import CaseState
from arc.domain.models import CaseEvent, PaymentCase

TERMINAL_CASE_STATES = frozenset(
    {CaseState.RECOVERED, CaseState.EXHAUSTED, CaseState.ESCALATED}
)

_ALLOWED_TRANSITIONS: dict[CaseState, frozenset[CaseState]] = {
    CaseState.DETECTED: frozenset(
        {
            CaseState.RECONCILING,
            CaseState.RECOVERED,
            CaseState.EXHAUSTED,
            CaseState.ESCALATED,
        }
    ),
    CaseState.RECONCILING: frozenset(
        {
            CaseState.DIAGNOSED,
            CaseState.RECOVERED,
            CaseState.EXHAUSTED,
            CaseState.ESCALATED,
        }
    ),
    CaseState.DIAGNOSED: frozenset(
        {
            CaseState.DECISIONED,
            CaseState.RECOVERED,
            CaseState.EXHAUSTED,
            CaseState.ESCALATED,
        }
    ),
    CaseState.DECISIONED: frozenset(
        {
            CaseState.POLICY_VALIDATED,
            CaseState.RECOVERED,
            CaseState.EXHAUSTED,
            CaseState.ESCALATED,
        }
    ),
    CaseState.POLICY_VALIDATED: frozenset(
        {
            CaseState.ACTIONED,
            CaseState.RECOVERED,
            CaseState.EXHAUSTED,
            CaseState.ESCALATED,
        }
    ),
    CaseState.ACTIONED: frozenset(
        {
            CaseState.WAITING_FOR_OUTCOME,
            CaseState.RECOVERED,
            CaseState.EXHAUSTED,
            CaseState.ESCALATED,
        }
    ),
    CaseState.WAITING_FOR_OUTCOME: TERMINAL_CASE_STATES,
    CaseState.RECOVERED: frozenset(),
    CaseState.EXHAUSTED: frozenset(),
    CaseState.ESCALATED: frozenset(),
}


class InvalidCaseTransition(ValueError):
    """Raised when a caller attempts a backwards or terminal transition."""


@dataclass(frozen=True, slots=True)
class CaseTransitionResult:
    """Result of applying or idempotently observing one transition."""

    previous_state: CaseState
    new_state: CaseState
    changed: bool
    audit_event: CaseEvent | None


def can_transition(current_state: CaseState, target_state: CaseState) -> bool:
    """Return whether a state change is idempotent or explicitly allowed."""

    return current_state == target_state or target_state in _ALLOWED_TRANSITIONS[
        current_state
    ]


def transition_case(
    session: Session,
    payment_case: PaymentCase,
    target_state: CaseState,
    *,
    reason_code: str,
    source: str,
    metadata: Mapping[str, Any] | None = None,
) -> CaseTransitionResult:
    """Validate, apply, and append one state transition audit event."""

    previous_state = payment_case.current_state
    if previous_state == target_state:
        return CaseTransitionResult(
            previous_state=previous_state,
            new_state=target_state,
            changed=False,
            audit_event=None,
        )

    if not can_transition(previous_state, target_state):
        raise InvalidCaseTransition(
            f"Case transition {previous_state.value} -> {target_state.value} is not allowed"
        )

    payment_case.current_state = target_state
    event_data = dict(metadata or {})
    event_data.update(
        {
            "previous_state": previous_state.value,
            "new_state": target_state.value,
            "reason_code": reason_code,
        }
    )
    audit_event = CaseEvent(
        case_id=payment_case.id,
        event_type="CASE_STATE_TRANSITION",
        source=source,
        event_data=event_data,
    )
    session.add(audit_event)
    return CaseTransitionResult(
        previous_state=previous_state,
        new_state=target_state,
        changed=True,
        audit_event=audit_event,
    )

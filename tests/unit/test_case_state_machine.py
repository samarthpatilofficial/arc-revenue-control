"""Unit tests for monotonic, audited ARC case lifecycle transitions."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from arc.domain.enums import CaseState
from arc.domain.models import CaseEvent, PaymentCase
from arc.reconciliation import InvalidCaseTransition, transition_case


def _case(state: CaseState) -> PaymentCase:
    return PaymentCase(
        id=uuid4(),
        case_reference=f"case_{uuid4().hex}",
        merchant_id="merchant_test",
        current_state=state,
    )


def _audit_events(session: Session) -> list[CaseEvent]:
    return [record for record in session.new if isinstance(record, CaseEvent)]


def test_detected_to_reconciling_is_allowed_and_audited() -> None:
    session = Session()
    payment_case = _case(CaseState.DETECTED)

    result = transition_case(
        session,
        payment_case,
        CaseState.RECONCILING,
        reason_code="TEST_RECONCILIATION",
        source="UNIT_TEST",
    )

    assert result.changed is True
    assert payment_case.current_state is CaseState.RECONCILING
    assert len(_audit_events(session)) == 1
    session.close()


def test_reconciling_to_diagnosed_is_available_for_next_task() -> None:
    session = Session()
    payment_case = _case(CaseState.RECONCILING)

    transition_case(
        session,
        payment_case,
        CaseState.DIAGNOSED,
        reason_code="TEST_FUTURE_DIAGNOSIS",
        source="UNIT_TEST",
    )

    assert payment_case.current_state is CaseState.DIAGNOSED
    session.close()


def test_backwards_transition_is_rejected() -> None:
    session = Session()
    payment_case = _case(CaseState.DIAGNOSED)

    with pytest.raises(InvalidCaseTransition, match="not allowed"):
        transition_case(
            session,
            payment_case,
            CaseState.RECONCILING,
            reason_code="TEST_BACKWARDS",
            source="UNIT_TEST",
        )

    assert payment_case.current_state is CaseState.DIAGNOSED
    assert _audit_events(session) == []
    session.close()


@pytest.mark.parametrize(
    "target_state",
    [CaseState.RECONCILING, CaseState.DETECTED],
)
def test_recovered_case_cannot_regress(target_state: CaseState) -> None:
    session = Session()
    payment_case = _case(CaseState.RECOVERED)

    with pytest.raises(InvalidCaseTransition):
        transition_case(
            session,
            payment_case,
            target_state,
            reason_code="TEST_TERMINAL_GUARD",
            source="UNIT_TEST",
        )

    assert payment_case.current_state is CaseState.RECOVERED
    session.close()


def test_same_state_transition_is_idempotent_without_duplicate_audit() -> None:
    session = Session()
    payment_case = _case(CaseState.RECONCILING)

    first = transition_case(
        session,
        payment_case,
        CaseState.RECONCILING,
        reason_code="TEST_IDEMPOTENT",
        source="UNIT_TEST",
    )
    second = transition_case(
        session,
        payment_case,
        CaseState.RECONCILING,
        reason_code="TEST_IDEMPOTENT",
        source="UNIT_TEST",
    )

    assert first.changed is False
    assert second.changed is False
    assert _audit_events(session) == []
    session.close()


def test_reconciling_can_resolve_early_to_recovered() -> None:
    session = Session()
    payment_case = _case(CaseState.RECONCILING)

    transition_case(
        session,
        payment_case,
        CaseState.RECOVERED,
        reason_code="AUTHORITATIVE_CAPTURE",
        source="UNIT_TEST",
    )

    assert payment_case.current_state is CaseState.RECOVERED
    assert len(_audit_events(session)) == 1
    session.close()

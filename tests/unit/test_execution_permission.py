"""Pure permission tests keeping policy authorization and approval distinct."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from arc.approval.permission import is_execution_permitted
from arc.domain.enums import ApprovalStatus, PolicyDecisionResult
from arc.domain.models import ApprovalRequest, PolicyDecision


def _decision(result: PolicyDecisionResult) -> PolicyDecision:
    return PolicyDecision(
        id=uuid4(),
        case_id=uuid4(),
        strategy_proposal_id=uuid4(),
        merchant_policy_id=None,
        strategy_input_fingerprint="a" * 64,
        policy_fingerprint="b" * 64,
        authorization_input_fingerprint="c" * 64,
        result=result,
        reason_code="TEST",
        explanation="Synthetic bounded decision.",
        recovery_window_ends_at=None,
        approval_threshold_minor=None,
        high_value_threshold_minor=None,
        observed_high_value=None,
        observed_amount_minor=1000,
        observed_attempt_count=0,
        observed_contact_attempt_count=0,
        evaluated_at=datetime.now(UTC),
    )


def _approval(
    decision: PolicyDecision,
    status: ApprovalStatus,
) -> ApprovalRequest:
    return ApprovalRequest(
        id=uuid4(),
        case_id=decision.case_id,
        policy_decision_id=decision.id,
        status=status,
    )


def test_authorized_current_decision_is_executable() -> None:
    assert is_execution_permitted(
        _decision(PolicyDecisionResult.AUTHORIZED)
    )


@pytest.mark.parametrize(
    ("approval_status", "expected"),
    [
        (None, False),
        (ApprovalStatus.PENDING, False),
        (ApprovalStatus.APPROVED, True),
        (ApprovalStatus.REJECTED, False),
    ],
)
def test_approval_required_decision_needs_exact_approved_record(
    approval_status: ApprovalStatus | None,
    expected: bool,
) -> None:
    decision = _decision(PolicyDecisionResult.REQUIRES_APPROVAL)
    approval = (
        _approval(decision, approval_status)
        if approval_status is not None
        else None
    )
    assert is_execution_permitted(decision, approval) is expected


def test_blocked_decision_cannot_be_overridden_by_approval() -> None:
    decision = _decision(PolicyDecisionResult.BLOCKED)
    assert not is_execution_permitted(
        decision,
        _approval(decision, ApprovalStatus.APPROVED),
    )


def test_superseded_authorized_decision_is_not_executable() -> None:
    decision = _decision(PolicyDecisionResult.AUTHORIZED)
    decision.superseded_at = datetime.now(UTC)
    assert not is_execution_permitted(decision)


def test_approval_for_another_decision_is_not_executable() -> None:
    decision = _decision(PolicyDecisionResult.REQUIRES_APPROVAL)
    other = _decision(PolicyDecisionResult.REQUIRES_APPROVAL)
    assert not is_execution_permitted(
        decision,
        _approval(other, ApprovalStatus.APPROVED),
    )

"""PostgreSQL tests for irreversible, decision-scoped human approvals."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from arc.approval import (
    ApprovalDecisionConflictError,
    ApprovalNotAllowedError,
    HumanApprovalService,
)
from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    RecoveryAction,
)
from arc.domain.models import (
    ApprovalRequest,
    MerchantPolicy,
    PaymentCase,
    PolicyDecision,
)
from arc.execution import (
    ExecutionNotPermittedError,
    RecoveryExecutionService,
)
from arc.policy.service import MerchantAuthorizationService
from tests.execution_support import StubPaymentLinkGateway, prepare_policy_decision
from tests.reconciliation_support import SessionFactory, load_case_events


def _approval_service(
    session_factory: SessionFactory,
) -> HumanApprovalService:
    return HumanApprovalService(
        session_factory=session_factory,
        clock=lambda: datetime.now(UTC),
    )


def _required_approval(
    session_factory: SessionFactory,
    *,
    payment_id: str,
) -> tuple[PaymentCase, PolicyDecision]:
    payment_case, _proposal, decision = prepare_policy_decision(
        session_factory,
        payment_id=payment_id,
        action=RecoveryAction.CREATE_RECOVERY_LINK,
        amount=250_000,
        policy_overrides={"require_approval_above_minor": 200_000},
    )
    return payment_case, decision


def test_requires_approval_creates_one_pending_request_idempotently(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, decision = _required_approval(
        integration_session_factory,
        payment_id="pay_approval_pending",
    )
    service = _approval_service(integration_session_factory)

    first = service.ensure_approval_request(decision.id)
    second = service.ensure_approval_request(decision.id)

    assert first.status is ApprovalStatus.PENDING
    assert second.approval_request_id == first.approval_request_id
    assert second.idempotent is True
    with integration_session_factory() as session:
        approvals = list(session.scalars(select(ApprovalRequest)))
    assert len(approvals) == 1
    events = load_case_events(integration_session_factory, payment_case.id)
    assert sum(event.event_type == "APPROVAL_REQUESTED" for event in events) == 1


def test_authorized_policy_cannot_create_approval_request(
    integration_session_factory: SessionFactory,
) -> None:
    _case, _proposal, decision = prepare_policy_decision(
        integration_session_factory,
        payment_id="pay_approval_authorized",
        action=RecoveryAction.CREATE_RECOVERY_LINK,
    )

    with pytest.raises(ApprovalNotAllowedError):
        _approval_service(
            integration_session_factory
        ).ensure_approval_request(decision.id)


def test_blocked_or_terminal_policy_cannot_create_approval_request(
    integration_session_factory: SessionFactory,
) -> None:
    _case, _proposal, decision = prepare_policy_decision(
        integration_session_factory,
        payment_id="pay_approval_blocked",
        action=RecoveryAction.CREATE_RECOVERY_LINK,
        policy_overrides={"allowed_actions": []},
    )

    with pytest.raises(ApprovalNotAllowedError):
        _approval_service(
            integration_session_factory
        ).ensure_approval_request(decision.id)


def test_pending_to_approved_keeps_case_policy_validated(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, decision = _required_approval(
        integration_session_factory,
        payment_id="pay_approval_approved",
    )
    service = _approval_service(integration_session_factory)
    request = service.ensure_approval_request(decision.id)

    result = service.decide_approval(
        request.approval_request_id,
        ApprovalStatus.APPROVED,
        decided_by="operator-1",
        note="Reviewed synthetic high-value case.",
    )

    assert result.status is ApprovalStatus.APPROVED
    assert result.case_state is CaseState.POLICY_VALIDATED
    events = load_case_events(integration_session_factory, payment_case.id)
    assert any(event.event_type == "APPROVAL_APPROVED" for event in events)


def test_pending_to_rejected_escalates_without_recovery_action(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, decision = _required_approval(
        integration_session_factory,
        payment_id="pay_approval_rejected",
    )
    service = _approval_service(integration_session_factory)
    request = service.ensure_approval_request(decision.id)

    result = service.decide_approval(
        request.approval_request_id,
        ApprovalStatus.REJECTED,
        decided_by="operator-2",
    )

    assert result.status is ApprovalStatus.REJECTED
    assert result.case_state is CaseState.ESCALATED
    events = load_case_events(integration_session_factory, payment_case.id)
    assert any(event.event_type == "APPROVAL_REJECTED" for event in events)


@pytest.mark.parametrize(
    "terminal_status",
    [ApprovalStatus.APPROVED, ApprovalStatus.REJECTED],
)
def test_same_terminal_decision_is_idempotent(
    integration_session_factory: SessionFactory,
    terminal_status: ApprovalStatus,
) -> None:
    _case, decision = _required_approval(
        integration_session_factory,
        payment_id=f"pay_approval_repeat_{terminal_status.value.lower()}",
    )
    service = _approval_service(integration_session_factory)
    request = service.ensure_approval_request(decision.id)
    first = service.decide_approval(
        request.approval_request_id,
        terminal_status,
        decided_by="operator-repeat",
    )
    second = service.decide_approval(
        request.approval_request_id,
        terminal_status,
        decided_by="different-operator",
    )

    assert second.approval_request_id == first.approval_request_id
    assert second.idempotent is True


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (ApprovalStatus.APPROVED, ApprovalStatus.REJECTED),
        (ApprovalStatus.REJECTED, ApprovalStatus.APPROVED),
    ],
)
def test_terminal_approval_cannot_reverse(
    integration_session_factory: SessionFactory,
    first: ApprovalStatus,
    second: ApprovalStatus,
) -> None:
    _case, decision = _required_approval(
        integration_session_factory,
        payment_id=f"pay_approval_reverse_{first.value.lower()}",
    )
    service = _approval_service(integration_session_factory)
    request = service.ensure_approval_request(decision.id)
    service.decide_approval(
        request.approval_request_id,
        first,
        decided_by="operator-first",
    )

    with pytest.raises(ApprovalDecisionConflictError):
        service.decide_approval(
            request.approval_request_id,
            second,
            decided_by="operator-second",
        )


def test_superseded_policy_decision_cannot_be_approved(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, decision = _required_approval(
        integration_session_factory,
        payment_id="pay_approval_superseded",
    )
    service = _approval_service(integration_session_factory)
    request = service.ensure_approval_request(decision.id)
    with integration_session_factory() as session:
        policy = session.scalar(
            select(MerchantPolicy).where(
                MerchantPolicy.merchant_id == payment_case.merchant_id
            )
        )
        assert policy is not None
        policy.require_approval_above_minor = 500_000
        session.commit()
    MerchantAuthorizationService(
        session_factory=integration_session_factory,
        clock=lambda: datetime.now(UTC),
    ).evaluate_policy(payment_case.id)

    with pytest.raises(ApprovalNotAllowedError):
        service.decide_approval(
            request.approval_request_id,
            ApprovalStatus.APPROVED,
            decided_by="operator-stale",
        )


def test_old_approval_grants_no_authority_to_new_policy_decision(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, old_decision = _required_approval(
        integration_session_factory,
        payment_id="pay_approval_policy_race",
    )
    service = _approval_service(integration_session_factory)
    old_request = service.ensure_approval_request(old_decision.id)
    service.decide_approval(
        old_request.approval_request_id,
        ApprovalStatus.APPROVED,
        decided_by="operator-race",
    )
    with integration_session_factory() as session:
        policy = session.scalar(
            select(MerchantPolicy).where(
                MerchantPolicy.merchant_id == payment_case.merchant_id
            )
        )
        assert policy is not None
        policy.max_automated_attempts = 4
        session.commit()
    new_decision = MerchantAuthorizationService(
        session_factory=integration_session_factory,
        clock=lambda: datetime.now(UTC),
    ).evaluate_policy(payment_case.id)

    assert new_decision.policy_decision_id != old_decision.id
    with integration_session_factory() as session:
        new_approval = session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.policy_decision_id
                == new_decision.policy_decision_id
            )
        )
    assert new_approval is None
    gateway = StubPaymentLinkGateway()
    with pytest.raises(ExecutionNotPermittedError):
        RecoveryExecutionService(
            session_factory=integration_session_factory,
            payment_link_gateway=gateway,
        ).execute(payment_case.id)
    assert gateway.calls == []

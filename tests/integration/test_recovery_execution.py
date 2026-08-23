"""PostgreSQL tests for crash-safe governed recovery execution."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID

import pytest
from sqlalchemy import func, select

from arc.approval import HumanApprovalService
from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    RecoveryAction,
    RecoveryExecutionStatus,
)
from arc.domain.models import (
    CaseEvent,
    MerchantPolicy,
    PaymentCase,
    RecoveryActionRecord,
)
from arc.execution import (
    ExecutionNotPermittedError,
    ExecutionRequiresPolicyReevaluationError,
    RecoveryExecutionService,
)
from arc.integrations.razorpay.payment_links import (
    PaymentLinkCreateRequest,
    PaymentLinkRejectedError,
    PaymentLinkUnavailableError,
    PaymentLinkUncertainError,
)
from arc.policy.service import MerchantAuthorizationService
from arc.reconciliation.state_machine import transition_case
from tests.execution_support import (
    StubPaymentLinkGateway,
    payment_link_snapshot,
    prepare_policy_decision,
)
from tests.reconciliation_support import SessionFactory, load_case_events


def _execute(
    session_factory: SessionFactory,
    gateway: StubPaymentLinkGateway | None = None,
    *,
    clock=lambda: datetime.now(UTC),
) -> RecoveryExecutionService:
    return RecoveryExecutionService(
        session_factory=session_factory,
        payment_link_gateway=gateway,
        clock=clock,
    )


def _load_action(
    session_factory: SessionFactory,
    case_id: UUID,
) -> RecoveryActionRecord:
    with session_factory() as session:
        record = session.scalar(
            select(RecoveryActionRecord).where(
                RecoveryActionRecord.case_id == case_id
            )
        )
        assert record is not None
        session.expunge(record)
        return record


def _load_case(
    session_factory: SessionFactory,
    case_id: UUID,
) -> PaymentCase:
    with session_factory() as session:
        payment_case = session.get(PaymentCase, case_id)
        assert payment_case is not None
        session.expunge(payment_case)
        return payment_case


def _prepare_external(
    session_factory: SessionFactory,
    *,
    payment_id: str,
    amount: int = 25_000,
    policy_overrides: dict[str, object] | None = None,
):
    return prepare_policy_decision(
        session_factory,
        payment_id=payment_id,
        action=RecoveryAction.CREATE_RECOVERY_LINK,
        amount=amount,
        policy_overrides=policy_overrides,
    )


def test_create_recovery_link_succeeds_once_with_stable_minimal_request(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_success",
    )
    gateway = StubPaymentLinkGateway()

    result = _execute(
        integration_session_factory,
        gateway,
    ).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    record = _load_action(integration_session_factory, payment_case.id)
    assert result.execution_status is RecoveryExecutionStatus.SUCCEEDED
    assert result.case_state is CaseState.WAITING_FOR_OUTCOME
    assert record.policy_decision_id == decision.id
    assert record.external_reference == f"arc_{record.id.hex}"
    assert len(record.external_reference) == 36
    assert record.external_url == "https://rzp.io/i/arc-test"
    assert record.execution_attempt_count == 1
    assert stored.attempt_count == 1
    assert stored.contact_attempt_count == 1
    assert [operation for operation, _value in gateway.calls] == [
        "lookup",
        "create",
    ]
    request = gateway.requests[0].model_dump(mode="json")
    assert request == {
        "amount": 25_000,
        "currency": "INR",
        "accept_partial": False,
        "reference_id": record.external_reference,
        "description": "ARC recovery payment",
        "expire_by": int(record.external_expires_at.timestamp()),
        "notify": {"sms": False, "email": False},
        "reminder_enable": False,
    }


def test_duplicate_execute_returns_same_row_without_network_or_counters(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_duplicate",
    )
    first_gateway = StubPaymentLinkGateway()
    first = _execute(
        integration_session_factory,
        first_gateway,
    ).execute(payment_case.id)
    second_gateway = StubPaymentLinkGateway()

    second = _execute(
        integration_session_factory,
        second_gateway,
    ).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    with integration_session_factory() as session:
        count = session.scalar(
            select(func.count()).select_from(RecoveryActionRecord)
        )
    assert second.recovery_action_id == first.recovery_action_id
    assert second.idempotent is True
    assert count == 1
    assert stored.attempt_count == 1
    assert stored.contact_attempt_count == 1
    assert second_gateway.calls == []


def test_wait_is_internal_succeeds_without_counters_or_provider_call(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = prepare_policy_decision(
        integration_session_factory,
        payment_id="pay_execute_wait",
        action=RecoveryAction.WAIT,
        re_evaluate_after_seconds=120,
    )
    gateway = StubPaymentLinkGateway()

    result = _execute(
        integration_session_factory,
        gateway,
    ).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    record = _load_action(integration_session_factory, payment_case.id)
    assert result.execution_status is RecoveryExecutionStatus.SUCCEEDED
    assert stored.current_state is CaseState.WAITING_FOR_OUTCOME
    assert stored.attempt_count == 0
    assert stored.contact_attempt_count == 0
    assert record.provider == "INTERNAL"
    assert record.next_evaluation_at is not None
    assert gateway.calls == []


def test_escalate_to_human_is_internal_and_moves_to_escalated(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = prepare_policy_decision(
        integration_session_factory,
        payment_id="pay_execute_escalate",
        action=RecoveryAction.ESCALATE_TO_HUMAN,
    )

    result = _execute(integration_session_factory).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    assert result.execution_status is RecoveryExecutionStatus.SUCCEEDED
    assert stored.current_state is CaseState.ESCALATED
    assert stored.attempt_count == 0
    assert stored.contact_attempt_count == 0


def test_no_action_is_internal_and_moves_to_exhausted(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = prepare_policy_decision(
        integration_session_factory,
        payment_id="pay_execute_no_action",
        action=RecoveryAction.NO_ACTION,
    )

    result = _execute(integration_session_factory).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    assert result.execution_status is RecoveryExecutionStatus.SUCCEEDED
    assert stored.current_state is CaseState.EXHAUSTED
    assert stored.attempt_count == 0


@pytest.mark.parametrize(
    "action",
    [
        RecoveryAction.REQUEST_RETRY,
        RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE,
    ],
)
def test_unsupported_executor_fails_safely_without_provider_call(
    integration_session_factory: SessionFactory,
    action: RecoveryAction,
) -> None:
    payment_case, _proposal, _decision = prepare_policy_decision(
        integration_session_factory,
        payment_id=f"pay_execute_unsupported_{action.value.lower()}",
        action=action,
    )
    gateway = StubPaymentLinkGateway()

    result = _execute(
        integration_session_factory,
        gateway,
    ).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    assert result.execution_status is RecoveryExecutionStatus.FAILED
    assert result.reason_code == "EXECUTOR_ACTION_NOT_IMPLEMENTED"
    assert stored.current_state is CaseState.ESCALATED
    assert stored.attempt_count == 0
    assert stored.contact_attempt_count == 0
    assert gateway.calls == []


def test_changed_policy_requires_reevaluation_before_action_row_or_network(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_stale_policy",
    )
    with integration_session_factory() as session:
        policy = session.scalar(
            select(MerchantPolicy).where(
                MerchantPolicy.merchant_id == payment_case.merchant_id
            )
        )
        assert policy is not None
        policy.max_automated_attempts = 9
        session.commit()
    gateway = StubPaymentLinkGateway()

    with pytest.raises(ExecutionRequiresPolicyReevaluationError):
        _execute(
            integration_session_factory,
            gateway,
        ).execute(payment_case.id)

    assert gateway.calls == []
    with integration_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RecoveryActionRecord)
        ) == 0


def test_stale_assessment_requires_reevaluation_before_network(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_stale_assessment",
    )
    with integration_session_factory() as session:
        stored = session.get(PaymentCase, payment_case.id)
        assert stored is not None
        stored.razorpay_payment_status = "captured"
        session.commit()
    gateway = StubPaymentLinkGateway()

    with pytest.raises(ExecutionRequiresPolicyReevaluationError):
        _execute(
            integration_session_factory,
            gateway,
        ).execute(payment_case.id)

    assert gateway.calls == []


def test_terminal_case_cannot_begin_execution(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_terminal",
    )
    with integration_session_factory() as session:
        stored = session.get(PaymentCase, payment_case.id)
        assert stored is not None
        transition_case(
            session,
            stored,
            CaseState.RECOVERED,
            reason_code="SYNTHETIC_CAPTURE",
            source="TEST",
        )
        session.commit()

    with pytest.raises(ExecutionRequiresPolicyReevaluationError):
        _execute(
            integration_session_factory,
            StubPaymentLinkGateway(),
        ).execute(payment_case.id)


def test_expired_recovery_window_requires_policy_reevaluation(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_expired",
    )
    assert decision.recovery_window_ends_at is not None
    future = decision.recovery_window_ends_at + timedelta(seconds=1)

    with pytest.raises(ExecutionRequiresPolicyReevaluationError):
        _execute(
            integration_session_factory,
            StubPaymentLinkGateway(),
            clock=lambda: future,
        ).execute(payment_case.id)


def test_changed_counter_requires_policy_reevaluation(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_counter_changed",
    )
    with integration_session_factory() as session:
        stored = session.get(PaymentCase, payment_case.id)
        assert stored is not None
        stored.attempt_count += 1
        session.commit()

    with pytest.raises(ExecutionRequiresPolicyReevaluationError):
        _execute(
            integration_session_factory,
            StubPaymentLinkGateway(),
        ).execute(payment_case.id)


def test_high_value_case_executes_only_after_exact_approval(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_high_value",
        amount=250_000,
        policy_overrides={"require_approval_above_minor": 200_000},
    )
    gateway = StubPaymentLinkGateway()
    service = _execute(integration_session_factory, gateway)

    with pytest.raises(ExecutionNotPermittedError):
        service.execute(payment_case.id)
    approval_service = HumanApprovalService(
        session_factory=integration_session_factory
    )
    request = approval_service.ensure_approval_request(decision.id)
    approval_service.decide_approval(
        request.approval_request_id,
        ApprovalStatus.APPROVED,
        decided_by="operator-execution",
    )
    result = service.execute(payment_case.id)

    assert result.execution_status is RecoveryExecutionStatus.SUCCEEDED
    assert result.case_state is CaseState.WAITING_FOR_OUTCOME


def test_approval_rejection_never_creates_external_action(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_approval_rejected",
        amount=250_000,
        policy_overrides={"require_approval_above_minor": 200_000},
    )
    approval_service = HumanApprovalService(
        session_factory=integration_session_factory
    )
    request = approval_service.ensure_approval_request(decision.id)
    approval_service.decide_approval(
        request.approval_request_id,
        ApprovalStatus.REJECTED,
        decided_by="operator-reject",
    )
    gateway = StubPaymentLinkGateway()

    with pytest.raises(ExecutionRequiresPolicyReevaluationError):
        _execute(
            integration_session_factory,
            gateway,
        ).execute(payment_case.id)

    assert gateway.calls == []


def test_stale_execution_lease_is_reclaimed_and_attempt_count_increments(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_stale_lease",
    )
    crash_gateway = StubPaymentLinkGateway()
    crash_gateway.create_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        _execute(
            integration_session_factory,
            crash_gateway,
        ).execute(payment_case.id)
    with integration_session_factory() as session:
        record = session.scalar(select(RecoveryActionRecord))
        assert record is not None
        assert record.execution_status is RecoveryExecutionStatus.IN_PROGRESS
        record.execution_started_at = datetime.now(UTC) - timedelta(
            seconds=121
        )
        session.commit()

    result = _execute(
        integration_session_factory,
        StubPaymentLinkGateway(),
    ).execute(payment_case.id)

    assert result.execution_status is RecoveryExecutionStatus.SUCCEEDED
    assert result.execution_attempt_count == 2


def test_fresh_execution_lease_is_not_double_claimed(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_fresh_lease",
    )
    crash_gateway = StubPaymentLinkGateway()
    crash_gateway.create_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        _execute(
            integration_session_factory,
            crash_gateway,
        ).execute(payment_case.id)
    second_gateway = StubPaymentLinkGateway()

    result = _execute(
        integration_session_factory,
        second_gateway,
    ).execute(payment_case.id)

    assert result.execution_status is RecoveryExecutionStatus.IN_PROGRESS
    assert result.reason_code == "EXECUTION_ALREADY_PROCESSING"
    assert result.execution_attempt_count == 1
    assert second_gateway.calls == []


def test_uncertain_create_is_adopted_by_reference_on_retry_once(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_uncertain_adopt",
    )
    uncertain_gateway = StubPaymentLinkGateway()
    uncertain_gateway.create_error = PaymentLinkUncertainError(
        "Synthetic uncertain creation"
    )
    first = _execute(
        integration_session_factory,
        uncertain_gateway,
    ).execute(payment_case.id)
    record = _load_action(integration_session_factory, payment_case.id)
    assert record.external_reference is not None
    assert record.external_expires_at is not None
    request = PaymentLinkCreateRequest(
        amount=payment_case.amount,
        currency=payment_case.currency,
        reference_id=record.external_reference,
        expire_by=int(record.external_expires_at.timestamp()),
    )
    adopt_gateway = StubPaymentLinkGateway()
    adopt_gateway.lookup_results = [payment_link_snapshot(request=request)]

    second = _execute(
        integration_session_factory,
        adopt_gateway,
    ).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    assert first.execution_status is RecoveryExecutionStatus.INDETERMINATE
    assert second.execution_status is RecoveryExecutionStatus.SUCCEEDED
    assert second.execution_attempt_count == 2
    assert stored.attempt_count == 1
    assert stored.contact_attempt_count == 1
    assert [operation for operation, _value in adopt_gateway.calls] == [
        "lookup"
    ]


def test_ambiguous_lookup_is_indeterminate_and_never_creates(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_ambiguous_lookup",
    )
    gateway = StubPaymentLinkGateway()
    gateway.lookup_results = []
    gateway.create_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        _execute(
            integration_session_factory,
            gateway,
        ).execute(payment_case.id)
    record = _load_action(integration_session_factory, payment_case.id)
    assert record.external_reference is not None
    assert record.external_expires_at is not None
    request = PaymentLinkCreateRequest(
        amount=payment_case.amount,
        currency=payment_case.currency,
        reference_id=record.external_reference,
        expire_by=int(record.external_expires_at.timestamp()),
    )
    with integration_session_factory() as session:
        stored = session.get(RecoveryActionRecord, record.id)
        assert stored is not None
        stored.execution_started_at = datetime.now(UTC) - timedelta(seconds=121)
        session.commit()
    ambiguous = StubPaymentLinkGateway()
    ambiguous.lookup_results = [
        payment_link_snapshot(request=request, payment_link_id="plink_one"),
        payment_link_snapshot(request=request, payment_link_id="plink_two"),
    ]

    result = _execute(
        integration_session_factory,
        ambiguous,
    ).execute(payment_case.id)

    assert result.execution_status is RecoveryExecutionStatus.INDETERMINATE
    assert [operation for operation, _value in ambiguous.calls] == ["lookup"]


def test_two_concurrent_execute_calls_share_one_row_and_one_create(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_concurrent",
    )
    entered_create = Event()
    release_create = Event()
    gateway = StubPaymentLinkGateway()

    def pause_create() -> None:
        entered_create.set()
        assert release_create.wait(timeout=10)

    gateway.on_create = pause_create
    service = _execute(integration_session_factory, gateway)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(service.execute, payment_case.id)
        assert entered_create.wait(timeout=10)
        second_future = pool.submit(service.execute, payment_case.id)
        second = second_future.result(timeout=10)
        release_create.set()
        first = first_future.result(timeout=10)

    assert first.execution_status is RecoveryExecutionStatus.SUCCEEDED
    assert second.execution_status is RecoveryExecutionStatus.IN_PROGRESS
    assert second.reason_code == "EXECUTION_ALREADY_PROCESSING"
    assert sum(operation == "create" for operation, _value in gateway.calls) == 1
    with integration_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RecoveryActionRecord)
        ) == 1


def test_capture_race_keeps_recovered_and_cancels_created_link(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_capture_race",
    )
    gateway = StubPaymentLinkGateway()

    def capture_case() -> None:
        with integration_session_factory() as session:
            stored = session.get(PaymentCase, payment_case.id)
            assert stored is not None
            transition_case(
                session,
                stored,
                CaseState.RECOVERED,
                reason_code="AUTHORITATIVE_CAPTURE_DURING_EXECUTION",
                source="TEST_RACE",
            )
            session.commit()

    gateway.on_create = capture_case

    result = _execute(
        integration_session_factory,
        gateway,
    ).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    assert stored.current_state is CaseState.RECOVERED
    assert stored.attempt_count == 0
    assert stored.contact_attempt_count == 0
    assert result.execution_status is RecoveryExecutionStatus.CANCELLED
    assert [operation for operation, _value in gateway.calls] == [
        "lookup",
        "create",
        "cancel",
    ]


def test_capture_race_cancellation_failure_requires_compensation(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_compensation_required",
    )
    gateway = StubPaymentLinkGateway()

    def capture_case() -> None:
        with integration_session_factory() as session:
            stored = session.get(PaymentCase, payment_case.id)
            assert stored is not None
            transition_case(
                session,
                stored,
                CaseState.RECOVERED,
                reason_code="AUTHORITATIVE_CAPTURE_DURING_EXECUTION",
                source="TEST_RACE",
            )
            session.commit()

    gateway.on_create = capture_case
    gateway.cancel_error = PaymentLinkUnavailableError(
        "Synthetic cancellation failure"
    )

    result = _execute(
        integration_session_factory,
        gateway,
    ).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    assert stored.current_state is CaseState.RECOVERED
    assert stored.attempt_count == 0
    assert result.execution_status is (
        RecoveryExecutionStatus.COMPENSATION_REQUIRED
    )
    events = load_case_events(integration_session_factory, payment_case.id)
    assert any(
        event.event_type == "RECOVERY_ACTION_COMPENSATION_REQUIRED"
        for event in events
    )


def test_definite_provider_rejection_is_failed_without_counters(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_rejected",
    )
    gateway = StubPaymentLinkGateway()
    gateway.create_error = PaymentLinkRejectedError(
        "Synthetic bounded rejection"
    )

    result = _execute(
        integration_session_factory,
        gateway,
    ).execute(payment_case.id)

    stored = _load_case(integration_session_factory, payment_case.id)
    assert result.execution_status is RecoveryExecutionStatus.FAILED
    assert stored.current_state is CaseState.POLICY_VALIDATED
    assert stored.attempt_count == 0
    assert stored.contact_attempt_count == 0


def test_ledger_and_audit_store_no_raw_provider_payload(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _decision = _prepare_external(
        integration_session_factory,
        payment_id="pay_execute_no_raw_payload",
    )
    gateway = StubPaymentLinkGateway()
    _execute(
        integration_session_factory,
        gateway,
    ).execute(payment_case.id)

    with integration_session_factory() as session:
        record = session.scalar(select(RecoveryActionRecord))
        events = list(
            session.scalars(
                select(CaseEvent).where(CaseEvent.case_id == payment_case.id)
            )
        )
        assert record is not None
        serialized = " ".join(
            [
                str(record.__dict__),
                *(str(event.event_data) for event in events),
            ]
        )
    assert "Authorization" not in serialized
    assert "ci_only_secret" not in serialized
    assert "raw provider" not in serialized

"""PostgreSQL tests for deterministic merchant authorization decisions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from uuid import UUID

import pytest
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import IntegrityError

from arc.assessment import CaseAssessmentService
from arc.domain.enums import (
    CaseState,
    PolicyDecisionResult,
    RecoveryAction,
)
from arc.domain.models import (
    MerchantPolicy,
    PaymentCase,
    PolicyDecision,
    RecoveryActionRecord,
    StrategyProposal,
)
from arc.intelligence.schemas import (
    StrategyContext,
    StrategyModelResult,
    StrategyOutput,
)
from arc.intelligence.service import StrategyService
from arc.policy.authorization import is_execution_authorized
from arc.policy.service import (
    MerchantAuthorizationService,
    PolicyEvaluationNotAllowedError,
    PolicyProposalNotCurrentError,
)
from tests.reconciliation_support import (
    SessionFactory,
    StubRazorpayClient,
    load_case_events,
    load_cases,
    payment_snapshot,
    processor,
    store_event,
)


class StubStrategyClient:
    """Bounded strategy stub proving policy evaluation has no model call."""

    model = "gpt-5.6-luna"

    def __init__(self, action: RecoveryAction) -> None:
        self.action = action
        self.calls: list[StrategyContext] = []

    def propose(self, context: StrategyContext) -> StrategyModelResult:
        self.calls.append(context)
        return StrategyModelResult(
            output=StrategyOutput(
                action=self.action,
                explanation="Synthetic strategy for policy integration testing.",
                confidence=0.99,
                re_evaluate_after_seconds=None,
            ),
            provider_response_id="resp_policy_integration",
            model=self.model,
            input_tokens=10,
            output_tokens=5,
            total_tokens=15,
            latency_ms=3,
        )


def _decisioned_case(
    session_factory: SessionFactory,
    *,
    payment_id: str,
    action: RecoveryAction = RecoveryAction.REQUEST_RETRY,
    amount: int | None = 25_000,
    error_reason: str = "incorrect_otp",
    error_source: str = "customer",
) -> tuple[PaymentCase, StrategyProposal, StubStrategyClient]:
    razorpay = StubRazorpayClient()
    razorpay.payments[payment_id] = payment_snapshot(
        payment_id=payment_id,
        status="failed",
        error_reason=error_reason,
        error_source=error_source,
        amount=amount,
    )
    event_id = store_event(
        session_factory,
        event_type="payment.failed",
        payment_id=payment_id,
    )
    processor(session_factory, razorpay).process_webhook_event(event_id)
    payment_case = load_cases(session_factory)[0]
    assert payment_case.last_reconciled_at is not None
    CaseAssessmentService(
        session_factory=session_factory,
        clock=lambda: payment_case.last_reconciled_at + timedelta(seconds=1),
    ).assess_case(payment_case.id)
    client = StubStrategyClient(action)
    StrategyService(
        session_factory=session_factory,
        model_client=client,
        clock=lambda: datetime.now(UTC),
    ).generate_strategy(payment_case.id)
    stored = load_cases(session_factory)[0]
    with session_factory() as session:
        proposal = session.scalar(
            select(StrategyProposal).where(
                StrategyProposal.case_id == payment_case.id,
                StrategyProposal.superseded_at.is_(None),
            )
        )
        assert proposal is not None
        session.expunge(proposal)
    return stored, proposal, client


def _create_policy(
    session_factory: SessionFactory,
    *,
    merchant_id: str,
    **overrides: object,
) -> UUID:
    values: dict[str, object] = {
        "merchant_id": merchant_id,
        "automation_enabled": True,
        "allowed_actions": [
            RecoveryAction.REQUEST_RETRY.value,
            RecoveryAction.CREATE_RECOVERY_LINK.value,
            RecoveryAction.REQUEST_PAYMENT_METHOD_UPDATE.value,
        ],
        "max_automated_attempts": 3,
        "max_contact_attempts": 2,
        "recovery_window_minutes": 60,
        "high_value_threshold_minor": 50_000,
        "require_approval_above_minor": 100_000,
        "stopping_rules": {},
    }
    values.update(overrides)
    with session_factory() as session:
        policy = MerchantPolicy(**values)
        session.add(policy)
        session.commit()
        return policy.id


def _load_decisions(
    session_factory: SessionFactory,
    case_id: UUID,
) -> list[PolicyDecision]:
    with session_factory() as session:
        decisions = list(
            session.scalars(
                select(PolicyDecision)
                .where(PolicyDecision.case_id == case_id)
                .order_by(PolicyDecision.evaluated_at, PolicyDecision.id)
            )
        )
        for decision in decisions:
            session.expunge(decision)
        return decisions


def _authorize(
    session_factory: SessionFactory,
    case_id: UUID,
    *,
    clock=lambda: datetime.now(UTC),
) -> MerchantAuthorizationService:
    return MerchantAuthorizationService(
        session_factory=session_factory,
        clock=clock,
    )


def test_valid_policy_authorizes_persists_transitions_and_audits(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, proposal, client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_authorized",
    )
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
    )

    result = _authorize(
        integration_session_factory, payment_case.id
    ).evaluate_policy(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    decisions = _load_decisions(
        integration_session_factory, payment_case.id
    )
    events = load_case_events(integration_session_factory, payment_case.id)
    assert result.result is PolicyDecisionResult.AUTHORIZED
    assert result.case_state is CaseState.POLICY_VALIDATED
    assert result.strategy_proposal_id == proposal.id
    assert stored.current_state is CaseState.POLICY_VALIDATED
    assert stored.contact_attempt_count == 0
    assert len(decisions) == 1
    assert decisions[0].superseded_at is None
    assert is_execution_authorized(decisions[0]) is True
    assert sum(event.event_type == "POLICY_AUTHORIZED" for event in events) == 1
    assert len(client.calls) == 1
    assert "recovery_actions" in inspect(
        integration_session_factory.kw["bind"]
    ).get_table_names()
    with integration_session_factory() as session:
        assert (
            session.scalar(
                select(func.count()).select_from(RecoveryActionRecord)
            )
            == 0
        )


def test_identical_evaluation_is_idempotent_without_duplicate_audit(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_idempotent",
    )
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
    )
    service = _authorize(integration_session_factory, payment_case.id)
    first = service.evaluate_policy(payment_case.id)
    event_count = len(
        load_case_events(integration_session_factory, payment_case.id)
    )
    second = service.evaluate_policy(payment_case.id)

    assert first.policy_decision_id == second.policy_decision_id
    assert second.idempotent is True
    assert len(_load_decisions(integration_session_factory, payment_case.id)) == 1
    assert (
        len(load_case_events(integration_session_factory, payment_case.id))
        == event_count
    )


def test_high_value_case_requires_approval_and_is_not_executable(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_high_value",
        action=RecoveryAction.CREATE_RECOVERY_LINK,
        amount=250_000,
    )
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
        high_value_threshold_minor=150_000,
        require_approval_above_minor=200_000,
    )

    result = _authorize(
        integration_session_factory, payment_case.id
    ).evaluate_policy(payment_case.id)

    decision = _load_decisions(
        integration_session_factory, payment_case.id
    )[0]
    events = load_case_events(integration_session_factory, payment_case.id)
    audit = next(
        event for event in events if event.event_type == "POLICY_REQUIRES_APPROVAL"
    )
    assert result.result is PolicyDecisionResult.REQUIRES_APPROVAL
    assert result.reason_code == "AMOUNT_REQUIRES_HUMAN_APPROVAL"
    assert result.case_state is CaseState.POLICY_VALIDATED
    assert decision.strategy_proposal_id == proposal.id
    assert decision.observed_amount_minor == 250_000
    assert decision.approval_threshold_minor == 200_000
    assert decision.observed_high_value is True
    assert is_execution_authorized(decision) is False
    assert audit.event_data["observed_amount_minor"] == 250_000
    assert audit.event_data["approval_threshold_minor"] == 200_000
    assert not any(event.event_type == "ACTION_EXECUTED" for event in events)


@pytest.mark.parametrize(
    ("policy_values", "reason"),
    [
        ({"allowed_actions": []}, "ACTION_NOT_ALLOWED_BY_POLICY"),
        (
            {"allowed_actions": ["FUTURE_UNKNOWN_ACTION"]},
            "POLICY_CONFIGURATION_INVALID",
        ),
    ],
)
def test_control_configuration_blocks_and_escalates(
    integration_session_factory: SessionFactory,
    policy_values: dict[str, object],
    reason: str,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id=f"pay_policy_control_{reason.lower()}",
    )
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
        **policy_values,
    )

    result = _authorize(
        integration_session_factory, payment_case.id
    ).evaluate_policy(payment_case.id)

    assert result.result is PolicyDecisionResult.BLOCKED
    assert result.reason_code == reason
    assert result.case_state is CaseState.ESCALATED


def test_missing_policy_external_action_blocks_and_escalates(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_missing",
    )

    result = _authorize(
        integration_session_factory, payment_case.id
    ).evaluate_policy(payment_case.id)

    decision = _load_decisions(
        integration_session_factory, payment_case.id
    )[0]
    assert result.reason_code == "POLICY_NOT_CONFIGURED"
    assert result.case_state is CaseState.ESCALATED
    assert decision.merchant_policy_id is None
    assert is_execution_authorized(decision) is False


def test_rule_source_does_not_bypass_policy_but_safe_escalation_authorizes(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, proposal, client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_rule_safe",
        error_reason="future_unknown_reason",
        error_source="business",
    )
    assert proposal.action is RecoveryAction.ESCALATE_TO_HUMAN

    result = _authorize(
        integration_session_factory, payment_case.id
    ).evaluate_policy(payment_case.id)

    assert result.result is PolicyDecisionResult.AUTHORIZED
    assert result.reason_code == "SAFE_INTERNAL_HUMAN_ESCALATION"
    assert result.case_state is CaseState.POLICY_VALIDATED
    assert client.calls == []


@pytest.mark.parametrize(
    ("case_updates", "policy_updates", "reason"),
    [
        (
            {"attempt_count": 3},
            {},
            "MAX_AUTOMATED_ATTEMPTS_REACHED",
        ),
        (
            {"contact_attempt_count": 2},
            {},
            "MAX_CUSTOMER_CONTACTS_REACHED",
        ),
        (
            {},
            {
                "stopping_rules": {
                    "blocked_failure_categories": [
                        "CUSTOMER_AUTHENTICATION"
                    ]
                }
            },
            "STOPPING_RULE_FAILURE_CATEGORY",
        ),
    ],
)
def test_hard_stops_block_and_exhaust(
    integration_session_factory: SessionFactory,
    case_updates: dict[str, object],
    policy_updates: dict[str, object],
    reason: str,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id=f"pay_policy_hard_{reason.lower()}",
        action=(
            RecoveryAction.CREATE_RECOVERY_LINK
            if "CONTACT" in reason
            else RecoveryAction.REQUEST_RETRY
        ),
    )
    with integration_session_factory() as session:
        stored = session.get(PaymentCase, payment_case.id)
        assert stored is not None
        for field, value in case_updates.items():
            setattr(stored, field, value)
        session.commit()
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
        **policy_updates,
    )

    result = _authorize(
        integration_session_factory, payment_case.id
    ).evaluate_policy(payment_case.id)

    assert result.result is PolicyDecisionResult.BLOCKED
    assert result.reason_code == reason
    assert result.case_state is CaseState.EXHAUSTED


def test_changed_policy_supersedes_current_decision_without_backwards_state(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_changed",
    )
    policy_id = _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
    )
    service = _authorize(integration_session_factory, payment_case.id)
    first = service.evaluate_policy(payment_case.id)
    with integration_session_factory() as session:
        policy = session.get(MerchantPolicy, policy_id)
        assert policy is not None
        policy.allowed_actions = []
        session.commit()

    second = service.evaluate_policy(payment_case.id)

    decisions = _load_decisions(
        integration_session_factory, payment_case.id
    )
    events = load_case_events(integration_session_factory, payment_case.id)
    assert first.result is PolicyDecisionResult.AUTHORIZED
    assert second.result is PolicyDecisionResult.BLOCKED
    assert second.reason_code == "ACTION_NOT_ALLOWED_BY_POLICY"
    assert second.case_state is CaseState.ESCALATED
    assert len(decisions) == 2
    assert decisions[0].superseded_at is not None
    assert decisions[1].superseded_at is None
    assert is_execution_authorized(decisions[0]) is False
    assert is_execution_authorized(decisions[1]) is False
    assert sum(event.event_type == "POLICY_REEVALUATED" for event in events) == 1
    policy_transitions = [
        event
        for event in events
        if event.event_type == "CASE_STATE_TRANSITION"
        and event.event_data.get("new_state") == CaseState.POLICY_VALIDATED.value
    ]
    assert len(policy_transitions) == 1


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("attempt_count", 1, "POLICY_AUTHORIZED"),
        ("contact_attempt_count", 1, "POLICY_AUTHORIZED"),
    ],
)
def test_changed_counters_create_new_current_decision(
    integration_session_factory: SessionFactory,
    field: str,
    value: int,
    reason: str,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id=f"pay_policy_counter_{field}",
        action=RecoveryAction.CREATE_RECOVERY_LINK,
    )
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
    )
    service = _authorize(integration_session_factory, payment_case.id)
    first = service.evaluate_policy(payment_case.id)
    with integration_session_factory() as session:
        stored = session.get(PaymentCase, payment_case.id)
        assert stored is not None
        setattr(stored, field, value)
        session.commit()

    second = service.evaluate_policy(payment_case.id)

    decisions = _load_decisions(
        integration_session_factory, payment_case.id
    )
    assert first.policy_decision_id != second.policy_decision_id
    assert second.reason_code == reason
    assert len(decisions) == 2
    assert decisions[0].superseded_at is not None
    assert decisions[1].superseded_at is None


def test_window_expiry_reevaluation_blocks_and_exhausts(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_window_expiry",
    )
    base = datetime.now(UTC)
    with integration_session_factory() as session:
        stored = session.get(PaymentCase, payment_case.id)
        assert stored is not None
        stored.detected_at = base
        session.commit()
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
        recovery_window_minutes=1,
    )
    current_time = [base + timedelta(seconds=30)]
    service = _authorize(
        integration_session_factory,
        payment_case.id,
        clock=lambda: current_time[0],
    )
    first = service.evaluate_policy(payment_case.id)
    current_time[0] = base + timedelta(seconds=90)

    second = service.evaluate_policy(payment_case.id)

    assert first.result is PolicyDecisionResult.AUTHORIZED
    assert second.result is PolicyDecisionResult.BLOCKED
    assert second.reason_code == "RECOVERY_WINDOW_EXPIRED"
    assert second.case_state is CaseState.EXHAUSTED


def test_superseded_or_stale_proposal_cannot_be_authorized(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_stale_proposal",
    )
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
    )
    with integration_session_factory() as session:
        stored_proposal = session.get(StrategyProposal, proposal.id)
        assert stored_proposal is not None
        stored_proposal.superseded_at = datetime.now(UTC)
        session.commit()

    with pytest.raises(PolicyProposalNotCurrentError):
        _authorize(
            integration_session_factory, payment_case.id
        ).evaluate_policy(
            payment_case.id,
            strategy_proposal_id=proposal.id,
        )

    with integration_session_factory() as session:
        stored_proposal = session.get(StrategyProposal, proposal.id)
        stored_case = session.get(PaymentCase, payment_case.id)
        assert stored_proposal is not None
        assert stored_case is not None
        stored_proposal.superseded_at = None
        stored_case.assessment_fingerprint = "0" * 64
        session.commit()

    with pytest.raises(PolicyProposalNotCurrentError):
        _authorize(
            integration_session_factory, payment_case.id
        ).evaluate_policy(payment_case.id)


@pytest.mark.parametrize("state", [CaseState.RECOVERED, CaseState.ACTIONED])
def test_terminal_or_actioned_case_cannot_be_evaluated(
    integration_session_factory: SessionFactory,
    state: CaseState,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id=f"pay_policy_invalid_state_{state.value.lower()}",
    )
    with integration_session_factory() as session:
        stored = session.get(PaymentCase, payment_case.id)
        assert stored is not None
        stored.current_state = state
        session.commit()

    with pytest.raises(PolicyEvaluationNotAllowedError):
        _authorize(
            integration_session_factory, payment_case.id
        ).evaluate_policy(payment_case.id)


def test_concurrent_evaluation_creates_one_current_decision_and_audit(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_concurrent",
    )
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
    )
    barrier = Barrier(2)

    def evaluate() -> UUID:
        barrier.wait(timeout=5)
        return _authorize(
            integration_session_factory, payment_case.id
        ).evaluate_policy(payment_case.id).policy_decision_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        decision_ids = list(executor.map(lambda _index: evaluate(), range(2)))

    decisions = _load_decisions(
        integration_session_factory, payment_case.id
    )
    events = load_case_events(integration_session_factory, payment_case.id)
    assert decision_ids[0] == decision_ids[1]
    assert len(decisions) == 1
    assert decisions[0].superseded_at is None
    assert sum(event.event_type == "POLICY_AUTHORIZED" for event in events) == 1


def test_database_prevents_two_current_decisions(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _proposal, _client = _decisioned_case(
        integration_session_factory,
        payment_id="pay_policy_unique_current",
    )
    _create_policy(
        integration_session_factory,
        merchant_id=payment_case.merchant_id,
    )
    _authorize(
        integration_session_factory, payment_case.id
    ).evaluate_policy(payment_case.id)
    original = _load_decisions(
        integration_session_factory, payment_case.id
    )[0]

    with integration_session_factory() as session:
        session.add(
            PolicyDecision(
                case_id=original.case_id,
                strategy_proposal_id=original.strategy_proposal_id,
                merchant_policy_id=original.merchant_policy_id,
                strategy_input_fingerprint=original.strategy_input_fingerprint,
                policy_fingerprint="1" * 64,
                authorization_input_fingerprint="2" * 64,
                result=PolicyDecisionResult.AUTHORIZED,
                reason_code="POLICY_AUTHORIZED",
                explanation="Synthetic conflicting current decision.",
                observed_attempt_count=0,
                observed_contact_attempt_count=0,
                evaluated_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()

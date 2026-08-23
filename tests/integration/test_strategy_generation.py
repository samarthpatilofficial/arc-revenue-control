"""PostgreSQL tests for bounded, fenced, idempotent strategy proposals."""

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from arc.assessment import CaseAssessmentService
from arc.config import Settings
from arc.domain.enums import (
    CaseState,
    RecoveryAction,
    StrategySource,
)
from arc.domain.models import PaymentCase, StrategyProposal
from arc.intelligence.errors import (
    StrategyConfigurationError,
    StrategyInvalidOutputError,
    StrategyNotAllowedError,
    StrategyRefusalError,
    StrategyStaleContextError,
    StrategyUnavailableError,
)
from arc.intelligence.schemas import (
    StrategyContext,
    StrategyModelResult,
    StrategyOutput,
)
from arc.intelligence.service import StrategyGenerationResult, StrategyService
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
    """Thread-safe injected model boundary that never performs network I/O."""

    model = "gpt-5.6-luna"

    def __init__(
        self,
        *,
        results: list[StrategyModelResult] | None = None,
        error: Exception | None = None,
        on_propose: Callable[[], None] | None = None,
    ) -> None:
        self.results = results or [_model_result()]
        self.error = error
        self.on_propose = on_propose
        self.calls: list[StrategyContext] = []
        self._lock = Lock()

    def propose(self, context: StrategyContext) -> StrategyModelResult:
        with self._lock:
            self.calls.append(context)
            result = self.results[min(len(self.calls) - 1, len(self.results) - 1)]
        if self.on_propose is not None:
            self.on_propose()
        if self.error is not None:
            raise self.error
        return result


def _model_result(
    action: RecoveryAction = RecoveryAction.REQUEST_RETRY,
    *,
    response_id: str = "resp_strategy_test",
) -> StrategyModelResult:
    return StrategyModelResult(
        output=StrategyOutput(
            action=action,
            explanation="Synthetic bounded proposal for an integration test.",
            confidence=0.81,
            re_evaluate_after_seconds=120,
        ),
        provider_response_id=response_id,
        model="gpt-5.6-luna",
        input_tokens=90,
        output_tokens=25,
        total_tokens=115,
        latency_ms=17,
    )


def _diagnosed_payment(
    session_factory: SessionFactory,
    *,
    payment_id: str,
    error_reason: str | None = "incorrect_otp",
    error_source: str | None = "customer",
) -> tuple[PaymentCase, StubRazorpayClient]:
    razorpay = StubRazorpayClient()
    razorpay.payments[payment_id] = payment_snapshot(
        payment_id=payment_id,
        status="failed",
        error_reason=error_reason,
        error_source=error_source,
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
    return load_cases(session_factory)[0], razorpay


def _service(
    session_factory: SessionFactory,
    client: StubStrategyClient,
) -> StrategyService:
    return StrategyService(
        session_factory=session_factory,
        model_client=client,
        clock=lambda: datetime.now(UTC),
    )


def _load_proposals(
    session_factory: SessionFactory,
    case_id: UUID,
) -> list[StrategyProposal]:
    with session_factory() as session:
        proposals = list(
            session.scalars(
                select(StrategyProposal)
                .where(StrategyProposal.case_id == case_id)
                .order_by(StrategyProposal.created_at, StrategyProposal.id)
            )
        )
        for proposal in proposals:
            session.expunge(proposal)
        return proposals


def test_ai_proposal_persists_transitions_and_audits_without_authority(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id="pay_strategy_ai",
    )
    client = StubStrategyClient()

    result = _service(
        integration_session_factory,
        client,
    ).generate_strategy(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    proposals = _load_proposals(
        integration_session_factory,
        payment_case.id,
    )
    events = load_case_events(integration_session_factory, payment_case.id)
    event_types = {event.event_type for event in events}
    assert result.idempotent is False
    assert result.source is StrategySource.AI
    assert result.action is RecoveryAction.REQUEST_RETRY
    assert result.reason_code == "AI_PROPOSED_REQUEST_RETRY"
    assert stored.current_state is CaseState.DECISIONED
    assert len(proposals) == 1
    assert proposals[0].provider_response_id == "resp_strategy_test"
    assert proposals[0].input_tokens == 90
    assert proposals[0].output_tokens == 25
    assert proposals[0].total_tokens == 115
    assert proposals[0].latency_ms == 17
    assert "STRATEGY_GENERATED" in event_types
    assert "CASE_STATE_TRANSITION" in event_types
    assert not any(event_type.startswith("POLICY_") for event_type in event_types)
    assert "ACTION_EXECUTED" not in event_types
    assert len(client.calls) == 1
    sent_context = client.calls[0].model_dump(mode="json")
    assert "payment_id" not in sent_context
    assert "customer_id" not in sent_context
    assert "error_description" not in sent_context


@pytest.mark.parametrize(
    ("error_reason", "error_source", "expected_reason"),
    [
        (
            "future_unknown_reason",
            "customer",
            "RULE_MANUAL_REVIEW_REQUIRED",
        ),
        (
            "future_unknown_reason",
            "business",
            "RULE_MERCHANT_FIX_REQUIRED",
        ),
    ],
)
def test_deterministic_dispositions_bypass_ai(
    integration_session_factory: SessionFactory,
    error_reason: str,
    error_source: str,
    expected_reason: str,
) -> None:
    payment_case, _razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id=f"pay_rule_{error_source}",
        error_reason=error_reason,
        error_source=error_source,
    )
    client = StubStrategyClient()

    result = _service(
        integration_session_factory,
        client,
    ).generate_strategy(payment_case.id)

    proposal = _load_proposals(
        integration_session_factory,
        payment_case.id,
    )[0]
    assert result.source is StrategySource.RULE
    assert result.action is RecoveryAction.ESCALATE_TO_HUMAN
    assert result.reason_code == expected_reason
    assert proposal.model is None
    assert proposal.provider_response_id is None
    assert client.calls == []


def test_repeat_request_is_idempotent_without_model_or_audit_duplication(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id="pay_strategy_idempotent",
    )
    client = StubStrategyClient()
    service = _service(integration_session_factory, client)

    first = service.generate_strategy(payment_case.id)
    event_count = len(
        load_case_events(integration_session_factory, payment_case.id)
    )
    second = service.generate_strategy(payment_case.id)

    assert first.proposal_id == second.proposal_id
    assert second.idempotent is True
    assert len(client.calls) == 1
    assert len(_load_proposals(integration_session_factory, payment_case.id)) == 1
    assert (
        len(load_case_events(integration_session_factory, payment_case.id))
        == event_count
    )


def test_strategy_input_fingerprint_is_database_unique(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id="pay_strategy_unique",
    )
    _service(
        integration_session_factory,
        StubStrategyClient(),
    ).generate_strategy(payment_case.id)
    original = _load_proposals(
        integration_session_factory,
        payment_case.id,
    )[0]

    with integration_session_factory() as session:
        session.add(
            StrategyProposal(
                case_id=original.case_id,
                assessment_fingerprint=original.assessment_fingerprint,
                strategy_input_fingerprint=(
                    original.strategy_input_fingerprint
                ),
                source=StrategySource.AI,
                action=RecoveryAction.REQUEST_RETRY,
                reason_code="AI_PROPOSED_REQUEST_RETRY",
                explanation="Synthetic duplicate proposal.",
                confidence=0.5,
                re_evaluate_after_seconds=60,
                prompt_version=original.prompt_version,
                model="gpt-5.6-luna",
                provider_response_id="resp_duplicate",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                latency_ms=1,
                superseded_at=datetime.now(UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()


def test_concurrent_same_input_persists_one_current_proposal(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id="pay_strategy_concurrent",
    )
    barrier = Barrier(2)
    client = StubStrategyClient(on_propose=lambda: barrier.wait(timeout=5))
    service = _service(integration_session_factory, client)

    def generate() -> StrategyGenerationResult:
        return service.generate_strategy(payment_case.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _value: generate(), range(2)))

    proposals = _load_proposals(integration_session_factory, payment_case.id)
    events = load_case_events(integration_session_factory, payment_case.id)
    assert len(client.calls) == 2
    assert len(proposals) == 1
    assert proposals[0].superseded_at is None
    assert results[0].proposal_id == results[1].proposal_id
    assert sum(result.idempotent for result in results) == 1
    assert sum(event.event_type == "STRATEGY_GENERATED" for event in events) == 1


def test_changed_assessment_regenerates_without_backwards_transition(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id="pay_strategy_regenerate",
    )
    client = StubStrategyClient(
        results=[
            _model_result(RecoveryAction.REQUEST_RETRY, response_id="resp_first"),
            _model_result(RecoveryAction.WAIT, response_id="resp_second"),
        ]
    )
    service = _service(integration_session_factory, client)
    first = service.generate_strategy(payment_case.id)

    razorpay.payments["pay_strategy_regenerate"] = payment_snapshot(
        payment_id="pay_strategy_regenerate",
        status="failed",
        error_reason="bank_technical_error",
        error_source="customer",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_strategy_regenerate",
    )
    processor(
        integration_session_factory,
        razorpay,
    ).process_webhook_event(event_id)
    reconciled = load_cases(integration_session_factory)[0]
    assert reconciled.last_reconciled_at is not None
    CaseAssessmentService(
        session_factory=integration_session_factory,
        clock=lambda: reconciled.last_reconciled_at + timedelta(seconds=1),
    ).assess_case(payment_case.id)

    second = service.generate_strategy(payment_case.id)

    proposals = _load_proposals(integration_session_factory, payment_case.id)
    stored = load_cases(integration_session_factory)[0]
    events = load_case_events(integration_session_factory, payment_case.id)
    assert first.proposal_id != second.proposal_id
    assert len(proposals) == 2
    assert proposals[0].superseded_at is not None
    assert proposals[1].superseded_at is None
    assert stored.current_state is CaseState.DECISIONED
    assert sum(event.event_type == "STRATEGY_REGENERATED" for event in events) == 1
    diagnosed_transitions = [
        event
        for event in events
        if event.event_type == "CASE_STATE_TRANSITION"
        and event.event_data.get("new_state") == CaseState.DECISIONED.value
    ]
    assert len(diagnosed_transitions) == 1


def test_payment_recovered_during_model_call_discards_stale_output(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id="pay_strategy_late_capture",
    )

    def capture_payment() -> None:
        razorpay.payments["pay_strategy_late_capture"] = payment_snapshot(
            payment_id="pay_strategy_late_capture",
            status="captured",
        )
        event_id = store_event(
            integration_session_factory,
            event_type="payment.captured",
            payment_id="pay_strategy_late_capture",
        )
        processor(
            integration_session_factory,
            razorpay,
        ).process_webhook_event(event_id)

    client = StubStrategyClient(on_propose=capture_payment)

    with pytest.raises(StrategyStaleContextError):
        _service(
            integration_session_factory,
            client,
        ).generate_strategy(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    events = load_case_events(integration_session_factory, payment_case.id)
    assert stored.current_state is CaseState.RECOVERED
    assert _load_proposals(integration_session_factory, payment_case.id) == []
    assert sum(
        event.event_type == "STRATEGY_DISCARDED_STALE_CONTEXT"
        for event in events
    ) == 1


def test_assessment_change_during_model_call_discards_stale_output(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id="pay_strategy_stale_assessment",
    )

    def change_assessment() -> None:
        razorpay.payments["pay_strategy_stale_assessment"] = payment_snapshot(
            payment_id="pay_strategy_stale_assessment",
            status="failed",
            error_reason="bank_technical_error",
            error_source="customer",
        )
        event_id = store_event(
            integration_session_factory,
            event_type="payment.failed",
            payment_id="pay_strategy_stale_assessment",
        )
        processor(
            integration_session_factory,
            razorpay,
        ).process_webhook_event(event_id)
        reconciled = load_cases(integration_session_factory)[0]
        assert reconciled.last_reconciled_at is not None
        CaseAssessmentService(
            session_factory=integration_session_factory,
            clock=lambda: reconciled.last_reconciled_at
            + timedelta(seconds=1),
        ).assess_case(payment_case.id)

    client = StubStrategyClient(on_propose=change_assessment)

    with pytest.raises(StrategyStaleContextError):
        _service(
            integration_session_factory,
            client,
        ).generate_strategy(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    assert stored.current_state is CaseState.DIAGNOSED
    assert _load_proposals(integration_session_factory, payment_case.id) == []


def test_incompatible_ai_action_is_rejected_without_state_change(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id="pay_strategy_incompatible",
        error_reason="bank_technical_error",
    )
    client = StubStrategyClient(
        results=[_model_result(RecoveryAction.CREATE_RECOVERY_LINK)]
    )

    with pytest.raises(StrategyNotAllowedError):
        _service(
            integration_session_factory,
            client,
        ).generate_strategy(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    events = load_case_events(integration_session_factory, payment_case.id)
    assert stored.current_state is CaseState.DIAGNOSED
    assert _load_proposals(integration_session_factory, payment_case.id) == []
    rejection = next(
        event
        for event in events
        if event.event_type == "STRATEGY_PROPOSAL_REJECTED"
    )
    assert (
        rejection.event_data["reason_code"]
        == "STRATEGY_INCOMPATIBLE_WITH_DIAGNOSIS"
    )


@pytest.mark.parametrize(
    "error",
    [
        StrategyUnavailableError("Strategy provider request timed out"),
        StrategyRefusalError("Strategy model refused the request"),
        StrategyInvalidOutputError("Strategy output was invalid"),
    ],
)
def test_model_failure_keeps_case_diagnosed_and_audits_safely(
    integration_session_factory: SessionFactory,
    error: Exception,
) -> None:
    payment_case, _razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id=f"pay_strategy_failure_{type(error).__name__}",
    )
    client = StubStrategyClient(error=error)

    with pytest.raises(type(error)):
        _service(
            integration_session_factory,
            client,
        ).generate_strategy(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    events = load_case_events(integration_session_factory, payment_case.id)
    assert stored.current_state is CaseState.DIAGNOSED
    assert _load_proposals(integration_session_factory, payment_case.id) == []
    failure = next(
        event
        for event in events
        if event.event_type == "STRATEGY_GENERATION_FAILED"
    )
    assert set(failure.event_data) == {
        "reason_code",
        "assessment_fingerprint",
        "strategy_input_fingerprint",
        "model",
        "prompt_version",
        "case_state",
    }


def test_missing_openai_key_fails_only_at_ai_generation(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _razorpay = _diagnosed_payment(
        integration_session_factory,
        payment_id="pay_strategy_missing_key",
    )
    settings = Settings(
        database_url=(
            "postgresql+psycopg://arc:test_only@localhost:5432/arc_test"
        ),
        openai_api_key=None,
        _env_file=None,
    )
    service = StrategyService(
        session_factory=integration_session_factory,
        settings=settings,
        clock=lambda: datetime.now(UTC),
    )

    with pytest.raises(StrategyConfigurationError):
        service.generate_strategy(payment_case.id)

    with integration_session_factory() as session:
        proposal_count = session.scalar(
            select(func.count()).select_from(StrategyProposal)
        )
    assert proposal_count == 0
    assert load_cases(integration_session_factory)[0].current_state is CaseState.DIAGNOSED

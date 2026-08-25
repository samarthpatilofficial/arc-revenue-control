"""PostgreSQL-backed contracts for judge-facing evidence separation."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from arc.config import Settings
from arc.demo import seed_demo_scenarios
from arc.demo.markers import OPENAI_EVIDENCE_CASE_REFERENCE
from arc.demo.openai_evidence import (
    OpenAIEvidenceConfigurationError,
    create_openai_evidence_case,
)
from arc.domain.enums import (
    ApprovalStatus,
    PolicyDecisionResult,
    ProviderMode,
    RecoveryAction,
)
from arc.domain.models import (
    ApprovalRequest,
    PaymentCase,
    RecoveryActionRecord,
    RecoveryAttribution,
    RecoveryOutcomeObservation,
    StrategyProposal,
)
from arc.evaluation.read_model import DEFAULT_EVALUATION_RESULT_PATH
from arc.intelligence.errors import StrategyInvalidOutputError
from arc.intelligence.schemas import (
    StrategyContext,
    StrategyModelResult,
    StrategyOutput,
)
from arc.outcomes import RecoveryOutcomeService, calculate_recovery_metrics
from arc.read_models.queries import (
    get_case_detail,
    get_case_timeline,
    list_case_summaries,
)
from arc.read_models.schemas import ResolutionKind, StrategyProvenance
from services.api.main import create_app
from tests.outcome_support import (
    TEST_SETTINGS,
    StubOutcomeGateway,
    outcome_snapshot,
    prepare_waiting_recovery,
)
from tests.reconciliation_support import SessionFactory


class StubOpenAIClient:
    """In-memory implementation of the existing strategy client boundary."""

    model = "gpt-5.6-luna"

    def __init__(self, *, malformed: bool = False) -> None:
        self.calls = 0
        self.malformed = malformed

    def propose(self, context: StrategyContext) -> StrategyModelResult:
        self.calls += 1
        assert context.amount_minor == 2_500_000
        if self.malformed:
            raise StrategyInvalidOutputError(
                "Model response failed strict local validation"
            )
        return StrategyModelResult(
            output=StrategyOutput(
                action=RecoveryAction.CREATE_RECOVERY_LINK,
                explanation="Use a bounded recovery checkout after human approval.",
                confidence=0.82,
                re_evaluate_after_seconds=None,
            ),
            provider_response_id="response-test-only",
            model=self.model,
            input_tokens=50,
            output_tokens=20,
            total_tokens=70,
            latency_ms=12,
        )


def _settings(*, key: str | None = "test-only-placeholder") -> Settings:
    return Settings(
        database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
        openai_api_key=key,
        _env_file=None,
    )


def test_already_captured_resolution_is_evidence_driven_and_not_attributed(
    integration_session_factory: SessionFactory,
) -> None:
    seed_demo_scenarios(
        settings=Settings(
            database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
            demo_mode=True,
            _env_file=None,
        ),
        session_factory=integration_session_factory,
    )
    with integration_session_factory() as session:
        stored = session.scalar(
            select(PaymentCase).where(
                PaymentCase.case_reference
                == "demo_already_captured_protection_v1"
            )
        )
        assert stored is not None
        stored.case_reference = "evidence_derived_captured_reference"
        session.commit()

    with integration_session_factory() as session:
        cases = list_case_summaries(
            session,
            state=None,
            failure_category=None,
            provider_mode=None,
            limit=100,
            offset=0,
        )
        captured = next(
            item
            for item in cases
            if item.resolution_kind is ResolutionKind.ALREADY_CAPTURED
        )
        detail = get_case_detail(session, captured.case_reference)

    assert detail is not None
    assert detail.case.resolution_kind is ResolutionKind.ALREADY_CAPTURED
    assert captured.strategy_provenance is StrategyProvenance.BYPASSED
    assert captured.recovered_amount_minor is None
    assert detail.execution is None
    assert detail.attribution is None


def test_strategy_provenance_uses_persisted_source_and_model_without_response_id(
    integration_session_factory: SessionFactory,
) -> None:
    seed_demo_scenarios(
        settings=Settings(
            database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
            demo_mode=True,
            _env_file=None,
        ),
        session_factory=integration_session_factory,
    )
    provider_case, _action, _decision = prepare_waiting_recovery(
        integration_session_factory,
        payment_id="pay_evidence_deterministic",
        amount=1_000,
    )
    create_openai_evidence_case(
        settings=_settings(),
        session_factory=integration_session_factory,
        model_client=StubOpenAIClient(),
    )

    with integration_session_factory() as session:
        offline = get_case_detail(session, "demo_high_value_approval_v1")
        deterministic = get_case_detail(session, provider_case.case_reference)
        openai = get_case_detail(session, OPENAI_EVIDENCE_CASE_REFERENCE)
        timeline = get_case_timeline(session, OPENAI_EVIDENCE_CASE_REFERENCE)

    assert offline is not None and offline.strategy is not None
    assert deterministic is not None and deterministic.strategy is not None
    assert openai is not None and openai.strategy is not None
    assert offline.strategy.provenance is StrategyProvenance.OFFLINE_SIMULATION
    assert deterministic.strategy.provenance is StrategyProvenance.DETERMINISTIC_RULE
    assert deterministic.strategy.model is None
    assert deterministic.strategy.confidence_authority is None
    assert openai.strategy.provenance is StrategyProvenance.OPENAI
    assert openai.strategy.model == "gpt-5.6-luna"
    assert timeline is not None
    assert any(item.title == "Synthetic case truth established" for item in timeline)
    assert all(item.title != "Razorpay state reconciled" for item in timeline)
    assert "provider_response_id" not in repr(openai.model_dump()).lower()
    assert "response-test-only" not in repr(openai.model_dump())


def test_evaluation_summary_endpoint_matches_tracked_aggregate() -> None:
    expected = json.loads(
        Path(DEFAULT_EVALUATION_RESULT_PATH).read_text(encoding="utf-8")
    )
    async def request() -> httpx.Response:
        transport = httpx.ASGITransport(app=create_app(_settings()))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            return await client.get("/api/v1/evaluation/summary")

    response = asyncio.run(request())

    assert response.status_code == 200
    payload = response.json()
    assert payload["evidence_class"] == "SYNTHETIC_EVALUATION"
    assert payload["status"] == "PASS"
    assert payload["metrics"] == expected["metrics"]
    assert "scenario_breakdown" not in payload
    assert "reproducibility" not in payload


def test_openai_evidence_stops_before_razorpay_execution_and_is_idempotent(
    integration_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbid_http(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("The injected evidence workflow must make no HTTP call")

    monkeypatch.setattr(httpx.Client, "request", forbid_http)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbid_http)
    client = StubOpenAIClient()

    first = create_openai_evidence_case(
        settings=_settings(),
        session_factory=integration_session_factory,
        model_client=client,
    )
    second = create_openai_evidence_case(
        settings=_settings(),
        session_factory=integration_session_factory,
        model_client=client,
    )

    assert first.policy_result is PolicyDecisionResult.REQUIRES_APPROVAL
    assert first.approval_pending is True
    assert second.idempotent is True
    assert client.calls == 1
    with integration_session_factory() as session:
        payment_case = session.scalar(
            select(PaymentCase).where(
                PaymentCase.case_reference == OPENAI_EVIDENCE_CASE_REFERENCE
            )
        )
        assert payment_case is not None
        assert session.scalar(
            select(func.count()).select_from(ApprovalRequest).where(
                ApprovalRequest.case_id == payment_case.id,
                ApprovalRequest.status == ApprovalStatus.PENDING,
            )
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(RecoveryActionRecord).where(
                RecoveryActionRecord.case_id == payment_case.id
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(RecoveryOutcomeObservation).where(
                RecoveryOutcomeObservation.case_id == payment_case.id
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution).where(
                RecoveryAttribution.case_id == payment_case.id
            )
        ) == 0


def test_missing_key_fails_before_database_access() -> None:
    called = False

    def forbidden_factory():
        nonlocal called
        called = True
        raise AssertionError("Missing-key failure must happen before database access")

    with pytest.raises(OpenAIEvidenceConfigurationError):
        create_openai_evidence_case(
            settings=_settings(key=None),
            session_factory=forbidden_factory,
        )

    assert called is False


def test_malformed_model_result_leaves_no_proposal_policy_or_execution(
    integration_session_factory: SessionFactory,
) -> None:
    with pytest.raises(StrategyInvalidOutputError):
        create_openai_evidence_case(
            settings=_settings(),
            session_factory=integration_session_factory,
            model_client=StubOpenAIClient(malformed=True),
        )

    with integration_session_factory() as session:
        payment_case = session.scalar(
            select(PaymentCase).where(
                PaymentCase.case_reference == OPENAI_EVIDENCE_CASE_REFERENCE
            )
        )
        assert payment_case is not None
        assert session.scalar(
            select(func.count()).select_from(StrategyProposal).where(
                StrategyProposal.case_id == payment_case.id
            )
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(RecoveryActionRecord).where(
                RecoveryActionRecord.case_id == payment_case.id
            )
        ) == 0
        detail = get_case_detail(session, OPENAI_EVIDENCE_CASE_REFERENCE)
        assert detail is not None
        assert detail.strategy is None
        assert detail.data_origin.value == "SYNTHETIC_INPUT"


def test_synthetic_openai_case_cannot_change_provider_recovery_metrics(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _decision = prepare_waiting_recovery(
        integration_session_factory,
        payment_id="pay_existing_provider_evidence",
        amount=1_000,
    )
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=1_000,
        payment_id="pay_existing_provider_recovered",
    )
    RecoveryOutcomeService(
        session_factory=integration_session_factory,
        payment_link_gateway=StubOutcomeGateway(snapshot),
        settings=TEST_SETTINGS,
    ).observe_recovery_action(action.id)

    with integration_session_factory() as session:
        before = calculate_recovery_metrics(
            session,
            provider_mode=ProviderMode.TEST,
            currency="INR",
        )

    create_openai_evidence_case(
        settings=_settings(),
        session_factory=integration_session_factory,
        model_client=StubOpenAIClient(),
    )

    with integration_session_factory() as session:
        after = calculate_recovery_metrics(
            session,
            provider_mode=ProviderMode.TEST,
            currency="INR",
        )
    assert before == after
    assert after.recovered_cases == 1
    assert after.recovered_revenue_minor == 1_000

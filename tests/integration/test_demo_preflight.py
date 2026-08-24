"""PostgreSQL-backed safety tests for the read-only demo preflight."""

import httpx
import pytest
from sqlalchemy import func, select

from arc.config import Settings
from arc.demo import seed_demo_scenarios
from arc.demo.preflight import render_demo_preflight, run_demo_preflight
from arc.domain.models import (
    ApprovalRequest,
    CaseEvent,
    MerchantPolicy,
    PaymentCase,
    PolicyDecision,
    RecoveryActionRecord,
    RecoveryAttribution,
    RecoveryOutcomeObservation,
    StrategyProposal,
    WebhookEvent,
)
from arc.outcomes import RecoveryOutcomeService
from tests.outcome_support import (
    TEST_SETTINGS,
    StubOutcomeGateway,
    outcome_snapshot,
    prepare_waiting_recovery,
)
from tests.reconciliation_support import SessionFactory

_COUNTED_MODELS = (
    RecoveryAttribution,
    RecoveryOutcomeObservation,
    RecoveryActionRecord,
    ApprovalRequest,
    PolicyDecision,
    StrategyProposal,
    CaseEvent,
    WebhookEvent,
    PaymentCase,
    MerchantPolicy,
)


def _demo_settings() -> Settings:
    return Settings(
        database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
        demo_mode=True,
        _env_file=None,
    )


def _seed_real_recovery(
    session_factory: SessionFactory,
) -> tuple[str, ...]:
    original_payment_id = "sensitive-original-marker"
    payment_link_id = "sensitive-link-marker"
    provider_payment_id = "sensitive-provider-marker"
    customer_id = "sensitive-customer-marker"
    payment_case, action, _ = prepare_waiting_recovery(
        session_factory,
        payment_id=original_payment_id,
        payment_link_id=payment_link_id,
        amount=1_000,
    )
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=1_000,
        payment_id=provider_payment_id,
    )
    RecoveryOutcomeService(
        session_factory=session_factory,
        payment_link_gateway=StubOutcomeGateway(snapshot),
        settings=TEST_SETTINGS,
    ).observe_recovery_action(action.id)
    with session_factory() as session:
        stored = session.get(PaymentCase, payment_case.id)
        assert stored is not None
        stored.customer_id = customer_id
        session.commit()
    return (
        original_payment_id,
        payment_link_id,
        provider_payment_id,
        customer_id,
    )


def _seed_ready_demo(session_factory: SessionFactory) -> tuple[str, ...]:
    sensitive_values = _seed_real_recovery(session_factory)
    seed_demo_scenarios(
        settings=_demo_settings(),
        session_factory=session_factory,
    )
    return sensitive_values


def _check(result, label: str):
    return next(item for item in result.checks if item.label == label)


def _counts(session_factory: SessionFactory) -> tuple[int, ...]:
    with session_factory() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in _COUNTED_MODELS
        )


def test_preflight_ready_with_expected_persisted_scenarios(
    integration_session_factory: SessionFactory,
) -> None:
    _seed_ready_demo(integration_session_factory)

    result = run_demo_preflight(
        session_factory=integration_session_factory,
    )

    assert result.ready is True
    assert all(item.ready for item in result.checks)
    assert render_demo_preflight(result).endswith("DEMO STATUS: READY")


def test_preflight_not_ready_without_real_attribution(
    integration_session_factory: SessionFactory,
) -> None:
    seed_demo_scenarios(
        settings=_demo_settings(),
        session_factory=integration_session_factory,
    )

    result = run_demo_preflight(
        session_factory=integration_session_factory,
    )

    assert result.ready is False
    assert _check(result, "Real TEST recovery").ready is False
    assert _check(result, "Evidence attribution").ready is False
    assert "DEMO STATUS: NOT READY" in render_demo_preflight(result)


def test_preflight_not_ready_without_reserved_synthetic_scenarios(
    integration_session_factory: SessionFactory,
) -> None:
    _seed_real_recovery(integration_session_factory)

    result = run_demo_preflight(
        session_factory=integration_session_factory,
    )

    assert result.ready is False
    assert _check(result, "Synthetic separation").ready is False
    assert _check(result, "High-value approval").ready is False
    assert _check(result, "Already-captured case").ready is False
    assert _check(result, "Hard-stop case").ready is False


def test_preflight_performs_no_writes_or_external_requests(
    integration_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_ready_demo(integration_session_factory)
    before = _counts(integration_session_factory)

    def forbid_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Demo preflight must remain offline")

    monkeypatch.setattr(httpx.Client, "request", forbid_network)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbid_network)

    result = run_demo_preflight(
        session_factory=integration_session_factory,
    )

    assert result.ready is True
    assert _counts(integration_session_factory) == before


def test_preflight_output_contains_no_sensitive_identifiers(
    integration_session_factory: SessionFactory,
) -> None:
    sensitive_values = _seed_ready_demo(integration_session_factory)

    output = render_demo_preflight(
        run_demo_preflight(session_factory=integration_session_factory)
    )

    for sensitive_value in sensitive_values:
        assert sensitive_value not in output
    assert "DATABASE_URL" not in output
    assert "postgresql" not in output.lower()
    assert "provider payment" not in output.lower()
    assert "https://" not in output

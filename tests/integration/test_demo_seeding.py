"""PostgreSQL safety tests for controlled offline demo scenario seeding."""

import httpx
import pytest
from sqlalchemy import func, select

from arc.config import Settings
from arc.demo import DemoModeDisabledError, seed_demo_scenarios
from arc.domain.enums import (
    ApprovalStatus,
    CaseState,
    PolicyDecisionResult,
)
from arc.domain.models import (
    ApprovalRequest,
    CaseEvent,
    PaymentCase,
    PolicyDecision,
    RecoveryActionRecord,
    RecoveryAttribution,
)
from arc.outcomes import RecoveryOutcomeService
from tests.outcome_support import (
    TEST_SETTINGS,
    StubOutcomeGateway,
    outcome_snapshot,
    prepare_waiting_recovery,
)
from tests.reconciliation_support import SessionFactory


def _settings(*, enabled: bool) -> Settings:
    return Settings(
        database_url="postgresql+psycopg://arc:test@localhost:5432/arc_test",
        demo_mode=enabled,
        _env_file=None,
    )


def test_demo_seeder_is_disabled_before_database_access_by_default() -> None:
    called = False

    def forbidden_factory():
        nonlocal called
        called = True
        raise AssertionError("Disabled seeder must not access the database")

    with pytest.raises(DemoModeDisabledError):
        seed_demo_scenarios(
            settings=_settings(enabled=False),
            session_factory=forbidden_factory,
        )

    assert called is False


def test_demo_seed_is_idempotent_offline_marked_and_preserves_real_case(
    integration_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory,
        payment_id="pay_existing_real_test_proof",
        amount=1_000,
    )
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=1_000,
        payment_id="pay_existing_real_recovered",
    )
    RecoveryOutcomeService(
        session_factory=integration_session_factory,
        payment_link_gateway=StubOutcomeGateway(snapshot),
        settings=TEST_SETTINGS,
    ).observe_recovery_action(action.id)
    with integration_session_factory() as session:
        existing = session.get(PaymentCase, payment_case.id)
        assert existing is not None
        before = (
            existing.current_state,
            existing.amount,
            existing.currency,
            existing.attempt_count,
            existing.contact_attempt_count,
            existing.resolved_at,
        )
        actions_before = session.scalar(
            select(func.count()).select_from(RecoveryActionRecord)
        )
        attributions_before = session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        )

    def forbid_network(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Demo seeding must remain offline")

    monkeypatch.setattr(httpx.Client, "request", forbid_network)
    monkeypatch.setattr(httpx.AsyncClient, "request", forbid_network)

    first = seed_demo_scenarios(
        settings=_settings(enabled=True),
        session_factory=integration_session_factory,
    )
    second = seed_demo_scenarios(
        settings=_settings(enabled=True),
        session_factory=integration_session_factory,
    )

    assert first.created_count == 3
    assert second.created_count == 0
    with integration_session_factory() as session:
        demo_cases = list(
            session.scalars(
                select(PaymentCase).where(
                    PaymentCase.case_reference.like("demo_%")
                )
            )
        )
        assert len(demo_cases) == 3
        by_reference = {item.case_reference: item for item in demo_cases}
        assert by_reference["demo_high_value_approval_v1"].amount == 2_500_000
        assert (
            by_reference["demo_high_value_approval_v1"].current_state
            is CaseState.POLICY_VALIDATED
        )
        assert (
            by_reference["demo_already_captured_protection_v1"].current_state
            is CaseState.RECOVERED
        )
        assert (
            by_reference["demo_hard_stop_attention_v1"].current_state
            is CaseState.EXHAUSTED
        )
        demo_ids = {item.id for item in demo_cases}
        markers = list(
            session.scalars(
                select(CaseEvent).where(
                    CaseEvent.case_id.in_(demo_ids),
                    CaseEvent.event_type == "DEMO_SCENARIO_SEEDED",
                    CaseEvent.source == "DEMO_SEED",
                )
            )
        )
        assert len(markers) == 3
        assert all(
            set(marker.event_data) == {"scenario_key", "synthetic"}
            and marker.event_data["synthetic"] is True
            for marker in markers
        )
        high_decision = session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.case_id
                == by_reference["demo_high_value_approval_v1"].id
            )
        )
        hard_stop_decision = session.scalar(
            select(PolicyDecision).where(
                PolicyDecision.case_id
                == by_reference["demo_hard_stop_attention_v1"].id
            )
        )
        approval = session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.case_id
                == by_reference["demo_high_value_approval_v1"].id
            )
        )
        assert high_decision is not None
        assert high_decision.result is PolicyDecisionResult.REQUIRES_APPROVAL
        assert approval is not None
        assert approval.status is ApprovalStatus.PENDING
        assert hard_stop_decision is not None
        assert hard_stop_decision.result is PolicyDecisionResult.BLOCKED
        assert hard_stop_decision.reason_code == "MAX_AUTOMATED_ATTEMPTS_REACHED"
        assert session.scalar(
            select(func.count())
            .select_from(RecoveryActionRecord)
            .where(RecoveryActionRecord.case_id.in_(demo_ids))
        ) == 0
        stored_existing = session.get(PaymentCase, payment_case.id)
        assert stored_existing is not None
        after = (
            stored_existing.current_state,
            stored_existing.amount,
            stored_existing.currency,
            stored_existing.attempt_count,
            stored_existing.contact_attempt_count,
            stored_existing.resolved_at,
        )
        assert after == before
        assert session.scalar(
            select(func.count()).select_from(RecoveryActionRecord)
        ) == actions_before
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == attributions_before

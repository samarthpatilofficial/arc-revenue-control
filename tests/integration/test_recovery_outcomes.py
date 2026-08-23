"""PostgreSQL-backed authoritative recovery observation and attribution tests."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arc.domain.enums import (
    CaseState,
    OutcomeObservationSource,
    ProviderMode,
    RecoveryOutcomeStatus,
)
from arc.domain.models import (
    CaseEvent,
    PaymentCase,
    RecoveryAttribution,
    RecoveryOutcomeObservation,
)
from arc.outcomes import (
    RecoveryOutcomeService,
    calculate_recovery_metrics,
    get_attribution_for_case,
    get_current_outcome_for_case,
    list_recovered_cases,
    list_waiting_for_outcome_cases,
    summarize_recovered_amount,
)
from arc.reconciliation.state_machine import transition_case
from tests.outcome_support import (
    TEST_SETTINGS,
    StubOutcomeGateway,
    outcome_snapshot,
    prepare_waiting_recovery,
)
from tests.reconciliation_support import SessionFactory


def _service(
    session_factory: SessionFactory,
    gateway: StubOutcomeGateway,
    *,
    mode: ProviderMode = ProviderMode.TEST,
) -> RecoveryOutcomeService:
    return RecoveryOutcomeService(
        session_factory=session_factory,
        payment_link_gateway=gateway,
        settings=TEST_SETTINGS,
        provider_mode=mode,
    )


def test_pending_observation_is_persisted_idempotently_without_counters(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, snapshot = prepare_waiting_recovery(
        integration_session_factory
    )
    gateway = StubOutcomeGateway(snapshot)
    service = _service(integration_session_factory, gateway)

    first = service.observe_recovery_action(action.id)
    duplicate = service.observe_recovery_action(
        action.id, source=OutcomeObservationSource.WEBHOOK_TRIGGERED
    )

    assert first.outcome_status is RecoveryOutcomeStatus.PENDING
    assert first.case_state is CaseState.WAITING_FOR_OUTCOME
    assert duplicate.idempotent is True
    assert duplicate.observation_id == first.observation_id
    with integration_session_factory() as session:
        stored_case = session.get(PaymentCase, payment_case.id)
        observations = session.scalar(
            select(func.count()).select_from(RecoveryOutcomeObservation)
        )
        attributions = session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        )
        assert stored_case is not None
        assert stored_case.attempt_count == 1
        assert stored_case.contact_attempt_count == 1
        assert observations == 1
        assert attributions == 0


def test_exact_paid_evidence_creates_one_attribution_and_recovers_case(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=payment_case.amount or 0,
        payment_id="pay_recovery_exact",
    )

    result = _service(
        integration_session_factory, StubOutcomeGateway(snapshot)
    ).observe_recovery_action(action.id)

    assert result.outcome_status is RecoveryOutcomeStatus.RECOVERED
    assert result.case_state is CaseState.RECOVERED
    assert result.recovered_amount_minor == payment_case.amount
    with integration_session_factory() as session:
        attribution = session.scalar(select(RecoveryAttribution))
        stored_case = session.get(PaymentCase, payment_case.id)
        assert attribution is not None
        assert attribution.provider_mode is ProviderMode.TEST
        assert attribution.recovered_amount_minor == payment_case.amount
        assert stored_case is not None
        assert stored_case.attempt_count == 1
        assert stored_case.contact_attempt_count == 1


def test_same_financial_truth_from_different_triggers_never_double_counts(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=payment_case.amount or 0,
        payment_id="pay_recovery_duplicate",
    )
    service = _service(integration_session_factory, StubOutcomeGateway(snapshot))

    first = service.observe_recovery_action(action.id)
    second = service.observe_recovery_action(
        action.id, source=OutcomeObservationSource.WEBHOOK_TRIGGERED
    )

    assert first.attribution_id == second.attribution_id
    assert second.idempotent is True
    with integration_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 1
        assert session.scalar(
            select(func.sum(RecoveryAttribution.recovered_amount_minor))
        ) == payment_case.amount


@pytest.mark.parametrize(
    ("provider_status", "outcome_status"),
    [
        ("expired", RecoveryOutcomeStatus.EXPIRED),
        ("cancelled", RecoveryOutcomeStatus.CANCELLED),
    ],
)
def test_zero_paid_terminal_link_exhausts_without_attribution(
    integration_session_factory: SessionFactory,
    provider_status: str,
    outcome_status: RecoveryOutcomeStatus,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    snapshot = outcome_snapshot(
        action, payment_case, status=provider_status
    )

    result = _service(
        integration_session_factory, StubOutcomeGateway(snapshot)
    ).observe_recovery_action(action.id)

    assert result.outcome_status is outcome_status
    assert result.case_state is CaseState.EXHAUSTED
    assert result.attribution_id is None


def test_partial_or_ambiguous_evidence_escalates_for_review(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="partially_paid",
        amount_paid=400,
    )

    result = _service(
        integration_session_factory, StubOutcomeGateway(snapshot)
    ).observe_recovery_action(action.id)

    assert result.outcome_status is RecoveryOutcomeStatus.REVIEW_REQUIRED
    assert result.case_state is CaseState.ESCALATED
    assert result.attribution_id is None


def test_already_recovered_case_without_attribution_requires_review(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    with integration_session_factory() as session:
        stored_case = session.get(PaymentCase, payment_case.id)
        assert stored_case is not None
        transition_case(
            session,
            stored_case,
            CaseState.RECOVERED,
            reason_code="INDEPENDENT_PAYMENT_RECOVERED",
            source="TEST_SETUP",
        )
        session.commit()
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=payment_case.amount or 0,
        payment_id="pay_late_recovery_link",
    )

    result = _service(
        integration_session_factory, StubOutcomeGateway(snapshot)
    ).observe_recovery_action(action.id)

    assert result.outcome_status is RecoveryOutcomeStatus.REVIEW_REQUIRED
    assert result.reason_code == "RECOVERY_ATTRIBUTION_CASE_ALREADY_RECOVERED"
    assert result.attribution_id is None


def test_one_action_cannot_receive_two_attributions(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    first_snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=payment_case.amount or 0,
        payment_id="pay_first_attribution",
        updated_at=1_725_000_100,
    )
    first = _service(
        integration_session_factory, StubOutcomeGateway(first_snapshot)
    ).observe_recovery_action(action.id)
    second_snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=payment_case.amount or 0,
        payment_id="pay_second_attribution",
        updated_at=1_725_000_200,
    )

    second = _service(
        integration_session_factory, StubOutcomeGateway(second_snapshot)
    ).observe_recovery_action(action.id)

    assert first.attribution_id is not None
    assert second.outcome_status is RecoveryOutcomeStatus.REVIEW_REQUIRED
    assert second.attribution_id == first.attribution_id
    with integration_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 1


def test_one_provider_payment_cannot_be_attributed_to_two_actions(
    integration_session_factory: SessionFactory,
) -> None:
    first_case, first_action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    shared_payment_id = "pay_shared_provider_evidence"
    first_snapshot = outcome_snapshot(
        first_action,
        first_case,
        status="paid",
        amount_paid=first_case.amount or 0,
        payment_id=shared_payment_id,
    )
    _service(
        integration_session_factory, StubOutcomeGateway(first_snapshot)
    ).observe_recovery_action(first_action.id)
    second_case, second_action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    second_snapshot = outcome_snapshot(
        second_action,
        second_case,
        status="paid",
        amount_paid=second_case.amount or 0,
        payment_id=shared_payment_id,
    )

    second = _service(
        integration_session_factory, StubOutcomeGateway(second_snapshot)
    ).observe_recovery_action(second_action.id)

    assert second.outcome_status is RecoveryOutcomeStatus.REVIEW_REQUIRED
    assert second.case_state is CaseState.ESCALATED
    with integration_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 1


def test_provider_modes_metrics_and_read_models_remain_separate(
    integration_session_factory: SessionFactory,
) -> None:
    for mode, suffix in ((ProviderMode.TEST, "test"), (ProviderMode.LIVE, "live")):
        payment_case, action, _ = prepare_waiting_recovery(
            integration_session_factory,
            payment_id=f"pay_original_{suffix}",
        )
        snapshot = outcome_snapshot(
            action,
            payment_case,
            status="paid",
            amount_paid=payment_case.amount or 0,
            payment_id=f"pay_recovered_{suffix}",
        )
        _service(
            integration_session_factory,
            StubOutcomeGateway(snapshot),
            mode=mode,
        ).observe_recovery_action(action.id)

    with integration_session_factory() as session:
        test_metrics = calculate_recovery_metrics(
            session, provider_mode=ProviderMode.TEST, currency="INR"
        )
        live_metrics = calculate_recovery_metrics(
            session, provider_mode=ProviderMode.LIVE, currency="INR"
        )
        summaries = summarize_recovered_amount(session)
        recovered_test = list_recovered_cases(
            session, provider_mode=ProviderMode.TEST, currency="INR"
        )
        assert test_metrics.recovered_cases == 1
        assert live_metrics.recovered_cases == 1
        assert len(summaries) == 2
        assert len(recovered_test) == 1
        assert get_attribution_for_case(session, recovered_test[0].id) is not None
        assert get_current_outcome_for_case(session, recovered_test[0].id) is not None
        assert list_waiting_for_outcome_cases(session) == []


def test_provider_fetch_occurs_after_first_row_lock_transaction_releases(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, snapshot = prepare_waiting_recovery(
        integration_session_factory
    )
    lock_verified = False

    def verify_rows_are_not_locked() -> None:
        nonlocal lock_verified
        with integration_session_factory() as session:
            assert session.scalar(
                select(PaymentCase)
                .where(PaymentCase.id == payment_case.id)
                .with_for_update(nowait=True)
            ) is not None
            lock_verified = True
            session.rollback()

    _service(
        integration_session_factory,
        StubOutcomeGateway(snapshot, on_fetch=verify_rows_are_not_locked),
    ).observe_recovery_action(action.id)

    assert lock_verified is True


def test_two_concurrent_paid_observers_create_one_attribution(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=payment_case.amount or 0,
        payment_id="pay_concurrent_recovery",
    )
    barrier = Barrier(2)
    gateway = StubOutcomeGateway(snapshot, on_fetch=lambda: barrier.wait())

    def observe() -> RecoveryOutcomeStatus:
        result = _service(
            integration_session_factory, gateway
        ).observe_recovery_action(action.id)
        return result.outcome_status

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(lambda _value: observe(), range(2)))

    assert statuses == [
        RecoveryOutcomeStatus.RECOVERED,
        RecoveryOutcomeStatus.RECOVERED,
    ]
    with integration_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RecoveryOutcomeObservation)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 1


def test_new_outcome_storage_and_audit_do_not_copy_pii_or_short_url(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=payment_case.amount or 0,
        payment_id="pay_sanitized_recovery",
    )
    _service(
        integration_session_factory, StubOutcomeGateway(snapshot)
    ).observe_recovery_action(action.id)

    with integration_session_factory() as session:
        observations = list(session.scalars(select(RecoveryOutcomeObservation)))
        attributions = list(session.scalars(select(RecoveryAttribution)))
        audit_events = list(
            session.scalars(
                select(CaseEvent).where(CaseEvent.case_id == payment_case.id)
                .where(CaseEvent.source == "RECOVERY_OBSERVER")
            )
        )
        persisted = repr(
            [observation.__dict__ for observation in observations]
            + [attribution.__dict__ for attribution in attributions]
            + [event.event_data for event in audit_events]
        )
        assert "must-not-be-persisted" not in persisted
        assert "customer" not in persisted.lower()
        assert "private@example" not in persisted

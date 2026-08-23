"""PostgreSQL-backed Payment Link webhook trigger processing tests."""

import pytest
from sqlalchemy import func, select

from arc.domain.enums import (
    CaseState,
    EventProcessingStatus,
    ProviderMode,
    RecoveryOutcomeStatus,
)
from arc.domain.models import (
    CaseEvent,
    PaymentCase,
    RecoveryAttribution,
    RecoveryOutcomeObservation,
    WebhookEvent,
)
from arc.integrations.razorpay.payment_links import PaymentLinkUnavailableError
from arc.outcomes import RecoveryOutcomeService
from arc.reconciliation import WebhookEventProcessor
from tests.outcome_support import (
    TEST_SETTINGS,
    StubOutcomeGateway,
    outcome_snapshot,
    prepare_waiting_recovery,
    store_payment_link_event,
)
from tests.reconciliation_support import (
    SessionFactory,
    StubRazorpayClient,
    payment_snapshot,
    store_event,
)


def _processor(
    session_factory: SessionFactory,
    gateway: StubOutcomeGateway,
) -> WebhookEventProcessor:
    observer = RecoveryOutcomeService(
        session_factory=session_factory,
        payment_link_gateway=gateway,
        settings=TEST_SETTINGS,
        provider_mode=ProviderMode.TEST,
    )
    return WebhookEventProcessor(
        session_factory=session_factory,
        razorpay_client=StubRazorpayClient(),
        recovery_outcome_observer=observer,
    )


def test_paid_webhook_matches_action_fetches_authoritatively_and_recovers(
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
        payment_id="pay_webhook_recovery",
    )
    attribution_absent_during_fetch = False

    def verify_fetch_precedes_attribution() -> None:
        nonlocal attribution_absent_during_fetch
        with integration_session_factory() as session:
            attribution_absent_during_fetch = (
                session.scalar(
                    select(func.count()).select_from(RecoveryAttribution)
                )
                == 0
            )

    gateway = StubOutcomeGateway(
        snapshot, on_fetch=verify_fetch_precedes_attribution
    )
    event_id = store_payment_link_event(
        integration_session_factory, action
    )

    result = _processor(
        integration_session_factory, gateway
    ).process_webhook_event(event_id)

    assert result.processing_status is EventProcessingStatus.PROCESSED
    assert result.case_id == payment_case.id
    assert gateway.calls == [action.external_reference_id]
    assert attribution_absent_during_fetch is True
    with integration_session_factory() as session:
        stored_case = session.get(PaymentCase, payment_case.id)
        observation = session.scalar(select(RecoveryOutcomeObservation))
        assert stored_case is not None
        assert stored_case.current_state is CaseState.RECOVERED
        assert observation is not None
        assert observation.outcome_status is RecoveryOutcomeStatus.RECOVERED


def test_duplicate_same_event_id_has_one_business_effect(
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
        payment_id="pay_same_event_duplicate",
    )
    gateway = StubOutcomeGateway(snapshot)
    event_id = store_payment_link_event(
        integration_session_factory, action, event_id="evt_same_paid"
    )
    processor = _processor(integration_session_factory, gateway)

    first = processor.process_webhook_event(event_id)
    duplicate = processor.process_webhook_event(event_id)

    assert first.processing_status is EventProcessingStatus.PROCESSED
    assert duplicate.idempotent is True
    assert gateway.calls == [action.external_reference_id]
    with integration_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 1


def test_two_event_ids_same_truth_create_one_observation_and_attribution(
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
        payment_id="pay_two_event_ids",
    )
    gateway = StubOutcomeGateway(snapshot)
    processor = _processor(integration_session_factory, gateway)
    first_event = store_payment_link_event(
        integration_session_factory, action, event_id="evt_paid_first"
    )
    second_event = store_payment_link_event(
        integration_session_factory, action, event_id="evt_paid_second"
    )

    processor.process_webhook_event(first_event)
    processor.process_webhook_event(second_event)

    assert len(gateway.calls) == 2
    with integration_session_factory() as session:
        assert session.scalar(
            select(func.count())
            .select_from(WebhookEvent)
            .where(WebhookEvent.event_type == "payment_link.paid")
        ) == 2
        assert session.scalar(
            select(func.count()).select_from(RecoveryOutcomeObservation)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 1


def test_unmatched_payment_link_webhook_is_safe_noop_without_case(
    integration_session_factory: SessionFactory,
) -> None:
    event_id = store_payment_link_event(
        integration_session_factory, None, event_type="payment_link.paid"
    )
    gateway = StubOutcomeGateway(
        PaymentLinkUnavailableError("Synthetic provider should not be called")
    )

    result = _processor(
        integration_session_factory, gateway
    ).process_webhook_event(event_id)

    assert result.processing_status is EventProcessingStatus.PROCESSED
    assert result.reason_code == "UNMATCHED_RECOVERY_PAYMENT_LINK_EVENT"
    assert gateway.calls == []
    with integration_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PaymentCase)) == 0
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 0


@pytest.mark.parametrize("provider_status", ["cancelled", "expired"])
def test_terminal_webhook_uses_authoritative_terminal_truth(
    integration_session_factory: SessionFactory,
    provider_status: str,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    snapshot = outcome_snapshot(
        action, payment_case, status=provider_status
    )
    event_id = store_payment_link_event(
        integration_session_factory,
        action,
        event_type=f"payment_link.{provider_status}",
    )

    result = _processor(
        integration_session_factory, StubOutcomeGateway(snapshot)
    ).process_webhook_event(event_id)

    assert result.processing_status is EventProcessingStatus.PROCESSED
    with integration_session_factory() as session:
        stored_case = session.get(PaymentCase, payment_case.id)
        assert stored_case is not None
        assert stored_case.current_state is CaseState.EXHAUSTED


def test_provider_read_failure_leaves_webhook_failed_and_retryable(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    event_id = store_payment_link_event(
        integration_session_factory, action
    )
    gateway = StubOutcomeGateway(
        PaymentLinkUnavailableError(
            "Razorpay Payment Link API is temporarily unavailable"
        )
    )

    processor = _processor(integration_session_factory, gateway)
    result = processor.process_webhook_event(event_id)

    assert result.processing_status is EventProcessingStatus.FAILED
    with integration_session_factory() as session:
        event = session.get(WebhookEvent, event_id)
        assert event is not None
        assert event.processing_status is EventProcessingStatus.FAILED
        assert event.processing_attempt_count == 1
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 0

    gateway.snapshot = outcome_snapshot(
        action,
        payment_case,
        status="paid",
        amount_paid=payment_case.amount or 0,
        payment_id="pay_retry_after_provider_failure",
    )
    retried = processor.process_webhook_event(event_id)

    assert retried.processing_status is EventProcessingStatus.PROCESSED
    with integration_session_factory() as session:
        event = session.get(WebhookEvent, event_id)
        assert event is not None
        assert event.processing_attempt_count == 2
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 1


def test_webhook_pii_remains_only_in_immutable_event_ledger(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, action, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    snapshot = outcome_snapshot(action, payment_case, status="created")
    event_id = store_payment_link_event(
        integration_session_factory,
        action,
        include_pii=True,
    )

    _processor(
        integration_session_factory, StubOutcomeGateway(snapshot)
    ).process_webhook_event(event_id)

    with integration_session_factory() as session:
        observation = session.scalar(select(RecoveryOutcomeObservation))
        outcome_audits = list(
            session.scalars(
                select(CaseEvent).where(
                    CaseEvent.source == "RECOVERY_OBSERVER"
                )
            )
        )
        assert observation is not None
        persisted_projection = repr(
            observation.__dict__
        ) + repr([event.event_data for event in outcome_audits])
        assert "private@example.test" not in persisted_projection
        assert "+910000000000" not in persisted_projection


def test_generic_payment_captured_never_creates_recovery_attribution(
    integration_session_factory: SessionFactory,
) -> None:
    payment_case, _, _ = prepare_waiting_recovery(
        integration_session_factory
    )
    assert payment_case.payment_id is not None
    razorpay = StubRazorpayClient()
    razorpay.payments[payment_case.payment_id] = payment_snapshot(
        payment_id=payment_case.payment_id,
        status="captured",
        amount=payment_case.amount or 1000,
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.captured",
        payment_id=payment_case.payment_id,
    )

    result = WebhookEventProcessor(
        session_factory=integration_session_factory,
        razorpay_client=razorpay,
    ).process_webhook_event(event_id)

    assert result.processing_status is EventProcessingStatus.PROCESSED
    with integration_session_factory() as session:
        assert session.scalar(
            select(func.count()).select_from(RecoveryAttribution)
        ) == 0

"""PostgreSQL tests for authoritative subscription reconciliation."""

from arc.domain.enums import CaseState, EventProcessingStatus
from tests.reconciliation_support import (
    SessionFactory,
    StubRazorpayClient,
    load_case_events,
    load_cases,
    load_event,
    processor,
    store_event,
    subscription_snapshot,
)


def test_pending_subscription_records_platform_retry_active(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.subscriptions["sub_pending"] = subscription_snapshot(
        subscription_id="sub_pending",
        status="pending",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_pending",
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    payment_case = load_cases(integration_session_factory)[0]
    assert result.reason_code == "PLATFORM_RETRY_ACTIVE"
    assert payment_case.current_state is CaseState.RECONCILING
    assert payment_case.razorpay_subscription_status == "pending"
    assert payment_case.customer_id == "cust_authoritative"
    assert payment_case.last_reconciled_at is not None
    assert payment_case.attempt_count == 0
    assert "PLATFORM_RETRY_ACTIVE" in {
        event.event_type
        for event in load_case_events(
            integration_session_factory,
            payment_case.id,
        )
    }


def test_halted_subscription_records_retry_exhaustion_without_action(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.subscriptions["sub_halted"] = subscription_snapshot(
        subscription_id="sub_halted",
        status="halted",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="subscription.halted",
        subscription_id="sub_halted",
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    payment_case = load_cases(integration_session_factory)[0]
    assert result.reason_code == "SUBSCRIPTION_RETRIES_EXHAUSTED"
    assert payment_case.current_state is CaseState.RECONCILING
    assert payment_case.razorpay_subscription_status == "halted"
    assert payment_case.attempt_count == 0


def test_stale_pending_signal_with_active_truth_creates_no_case(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.subscriptions["sub_active"] = subscription_snapshot(
        subscription_id="sub_active",
        status="active",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_active",
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    assert result.reason_code == "SUBSCRIPTION_ACTIVE_NO_RECOVERY_REQUIRED"
    assert result.case_id is None
    assert load_cases(integration_session_factory) == []


def test_halted_case_resolves_when_subscription_is_authoritatively_active(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.subscriptions["sub_reactivated"] = subscription_snapshot(
        subscription_id="sub_reactivated",
        status="halted",
    )
    service = processor(integration_session_factory, client)
    halted_event = store_event(
        integration_session_factory,
        event_type="subscription.halted",
        subscription_id="sub_reactivated",
        event_id="evt_reactivated_1",
    )
    service.process_webhook_event(halted_event)

    client.subscriptions["sub_reactivated"] = subscription_snapshot(
        subscription_id="sub_reactivated",
        status="active",
    )
    active_truth_event = store_event(
        integration_session_factory,
        event_type="subscription.halted",
        subscription_id="sub_reactivated",
        event_id="evt_reactivated_2",
    )
    service.process_webhook_event(active_truth_event)

    payment_case = load_cases(integration_session_factory)[0]
    assert payment_case.current_state is CaseState.RECOVERED
    assert payment_case.razorpay_subscription_status == "active"
    assert payment_case.resolved_at is not None


def test_stale_pending_signal_cannot_regress_halted_external_semantics(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.subscriptions["sub_stale_pending"] = subscription_snapshot(
        subscription_id="sub_stale_pending",
        status="halted",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_stale_pending",
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    payment_case = load_cases(integration_session_factory)[0]
    assert result.reason_code == "SUBSCRIPTION_RETRIES_EXHAUSTED"
    assert payment_case.razorpay_subscription_status == "halted"
    event_types = {
        event.event_type
        for event in load_case_events(
            integration_session_factory,
            payment_case.id,
        )
    }
    assert "SUBSCRIPTION_RETRIES_EXHAUSTED" in event_types
    assert "PLATFORM_RETRY_ACTIVE" not in event_types


def test_repeated_subscription_processing_is_idempotent(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.subscriptions["sub_idempotent"] = subscription_snapshot(
        subscription_id="sub_idempotent",
        status="pending",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_idempotent",
    )
    service = processor(integration_session_factory, client)

    first = service.process_webhook_event(event_id)
    payment_case = load_cases(integration_session_factory)[0]
    audit_count = len(
        load_case_events(integration_session_factory, payment_case.id)
    )
    second = service.process_webhook_event(event_id)

    assert first.processing_status is EventProcessingStatus.PROCESSED
    assert second.idempotent is True
    assert len(client.calls) == 1
    assert len(load_cases(integration_session_factory)) == 1
    assert (
        len(load_case_events(integration_session_factory, payment_case.id))
        == audit_count
    )


def test_subscription_customer_is_refreshed_from_api_truth(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.subscriptions["sub_customer"] = subscription_snapshot(
        subscription_id="sub_customer",
        status="pending",
        customer_id="cust_first",
    )
    service = processor(integration_session_factory, client)
    first_event = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_customer",
        event_id="evt_customer_1",
    )
    service.process_webhook_event(first_event)

    client.subscriptions["sub_customer"] = subscription_snapshot(
        subscription_id="sub_customer",
        status="pending",
        customer_id="cust_updated",
    )
    second_event = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_customer",
        event_id="evt_customer_2",
    )
    service.process_webhook_event(second_event)

    payment_case = load_cases(integration_session_factory)[0]
    assert payment_case.customer_id == "cust_updated"


def test_recovered_subscription_case_cannot_regress_on_later_pending_truth(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    service = processor(integration_session_factory, client)
    client.subscriptions["sub_terminal"] = subscription_snapshot(
        subscription_id="sub_terminal",
        status="pending",
    )
    pending_event = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_terminal",
        event_id="evt_terminal_1",
    )
    service.process_webhook_event(pending_event)

    client.subscriptions["sub_terminal"] = subscription_snapshot(
        subscription_id="sub_terminal",
        status="active",
    )
    active_event = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_terminal",
        event_id="evt_terminal_2",
    )
    service.process_webhook_event(active_event)
    assert load_cases(integration_session_factory)[0].current_state is CaseState.RECOVERED

    client.subscriptions["sub_terminal"] = subscription_snapshot(
        subscription_id="sub_terminal",
        status="pending",
    )
    later_pending_event = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_terminal",
        event_id="evt_terminal_3",
    )
    service.process_webhook_event(later_pending_event)

    payment_case = load_cases(integration_session_factory)[0]
    assert payment_case.current_state is CaseState.RECOVERED
    assert load_event(
        integration_session_factory,
        later_pending_event,
    ).processing_status is EventProcessingStatus.PROCESSED

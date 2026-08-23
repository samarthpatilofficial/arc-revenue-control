"""PostgreSQL tests for authoritative payment reconciliation."""

from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from arc.domain.enums import CaseState, EventProcessingStatus
from arc.domain.models import PaymentCase
from arc.persistence import get_or_create_case
from tests.reconciliation_support import (
    SessionFactory,
    StubRazorpayClient,
    load_case_events,
    load_cases,
    load_event,
    payment_snapshot,
    processor,
    store_event,
)


def test_failed_payment_is_reconciled_with_authoritative_metadata(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_failed"] = payment_snapshot(
        payment_id="pay_failed",
        status="failed",
        amount=18_501,
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_failed",
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    payment_case = load_cases(integration_session_factory)[0]
    assert result.processing_status is EventProcessingStatus.PROCESSED
    assert payment_case.current_state is CaseState.RECONCILING
    assert payment_case.razorpay_payment_status == "failed"
    assert payment_case.razorpay_payment_method == "card"
    assert payment_case.amount == 18_501
    assert isinstance(payment_case.amount, int)
    assert payment_case.currency == "INR"
    assert payment_case.customer_id == "cust_authoritative"
    assert payment_case.error_code == "BAD_REQUEST_ERROR"
    assert payment_case.error_source == "customer"
    assert payment_case.error_step == "payment_authentication"
    assert payment_case.error_reason == "incorrect_otp"
    assert payment_case.last_reconciled_at is not None
    assert payment_case.attempt_count == 0

    audit_events = load_case_events(
        integration_session_factory,
        payment_case.id,
    )
    assert {audit.event_type for audit in audit_events} >= {
        "CASE_DETECTED",
        "CASE_STATE_TRANSITION",
        "RECONCILIATION_CONFIRMED_FAILURE",
    }
    reconciliation_audit = next(
        audit
        for audit in audit_events
        if audit.event_type == "RECONCILIATION_CONFIRMED_FAILURE"
    )
    assert reconciliation_audit.event_data["external_status"] == "failed"
    assert reconciliation_audit.event_data["new_state"] == "RECONCILING"
    assert "payload" not in reconciliation_audit.event_data


def test_failed_webhook_with_captured_api_truth_resolves_recovered(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_already_captured"] = payment_snapshot(
        payment_id="pay_already_captured",
        status="captured",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_already_captured",
    )

    processor(integration_session_factory, client).process_webhook_event(event_id)

    payment_case = load_cases(integration_session_factory)[0]
    assert payment_case.current_state is CaseState.RECOVERED
    assert payment_case.razorpay_payment_status == "captured"
    assert payment_case.resolved_at is not None
    event_types = {
        event.event_type
        for event in load_case_events(
            integration_session_factory,
            payment_case.id,
        )
    }
    assert "RECONCILIATION_FOUND_ALREADY_CAPTURED" in event_types
    assert "RECONCILIATION_CONFIRMED_FAILURE" not in event_types


def test_failed_then_captured_finishes_recovered(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_late_capture"] = payment_snapshot(
        payment_id="pay_late_capture",
        status="failed",
    )
    failed_event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_late_capture",
        event_id="evt_failed_then_capture_1",
    )
    service = processor(integration_session_factory, client)
    service.process_webhook_event(failed_event_id)

    client.payments["pay_late_capture"] = payment_snapshot(
        payment_id="pay_late_capture",
        status="captured",
    )
    captured_event_id = store_event(
        integration_session_factory,
        event_type="payment.captured",
        payment_id="pay_late_capture",
        event_id="evt_failed_then_capture_2",
    )
    service.process_webhook_event(captured_event_id)

    cases = load_cases(integration_session_factory)
    assert len(cases) == 1
    assert cases[0].current_state is CaseState.RECOVERED
    assert cases[0].razorpay_payment_status == "captured"


def test_captured_then_stale_failed_uses_api_truth_without_regression(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_stale_failure"] = payment_snapshot(
        payment_id="pay_stale_failure",
        status="captured",
    )
    captured_event_id = store_event(
        integration_session_factory,
        event_type="payment.captured",
        payment_id="pay_stale_failure",
        event_id="evt_capture_before_stale_1",
    )
    service = processor(integration_session_factory, client)
    service.process_webhook_event(captured_event_id)
    assert load_cases(integration_session_factory) == []

    stale_failed_event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_stale_failure",
        event_id="evt_capture_before_stale_2",
    )
    service.process_webhook_event(stale_failed_event_id)

    payment_case = load_cases(integration_session_factory)[0]
    assert payment_case.current_state is CaseState.RECOVERED
    assert payment_case.razorpay_payment_status == "captured"
    event_types = {
        event.event_type
        for event in load_case_events(
            integration_session_factory,
            payment_case.id,
        )
    }
    assert "RECONCILIATION_CONFIRMED_FAILURE" not in event_types


def test_captured_payment_without_existing_case_does_not_create_one(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_no_case"] = payment_snapshot(
        payment_id="pay_no_case",
        status="captured",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.captured",
        payment_id="pay_no_case",
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    assert result.case_id is None
    assert result.reason_code == "CAPTURE_CONFIRMED_WITHOUT_RECOVERY_CASE"
    assert load_cases(integration_session_factory) == []


def test_unconfirmed_capture_signal_without_case_still_creates_no_case(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_capture_unconfirmed"] = payment_snapshot(
        payment_id="pay_capture_unconfirmed",
        status="failed",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.captured",
        payment_id="pay_capture_unconfirmed",
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    assert result.reason_code == "PAYMENT_CAPTURE_SIGNAL_NOT_CONFIRMED"
    assert load_cases(integration_session_factory) == []


def test_reprocessing_same_event_is_idempotent_without_duplicate_audit(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_idempotent"] = payment_snapshot(
        payment_id="pay_idempotent",
        status="failed",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_idempotent",
    )
    service = processor(integration_session_factory, client)

    first = service.process_webhook_event(event_id)
    payment_case = load_cases(integration_session_factory)[0]
    first_audit_count = len(
        load_case_events(integration_session_factory, payment_case.id)
    )
    second = service.process_webhook_event(event_id)

    assert first.idempotent is False
    assert second.idempotent is True
    assert len(client.calls) == 1
    assert len(load_cases(integration_session_factory)) == 1
    assert (
        len(load_case_events(integration_session_factory, payment_case.id))
        == first_audit_count
    )


def test_repeated_failure_events_resolve_one_logical_case(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_repeated"] = payment_snapshot(
        payment_id="pay_repeated",
        status="failed",
    )
    service = processor(integration_session_factory, client)

    for suffix in ("one", "two"):
        event_id = store_event(
            integration_session_factory,
            event_type="payment.failed",
            payment_id="pay_repeated",
            event_id=f"evt_repeated_{suffix}",
        )
        service.process_webhook_event(event_id)

    assert len(load_cases(integration_session_factory)) == 1


def test_concurrent_case_creation_uses_database_conflict_protection(
    integration_session_factory: SessionFactory,
) -> None:
    def create_case() -> tuple[object, bool]:
        with integration_session_factory() as session:
            result = get_or_create_case(
                session,
                identity_kind="payment",
                external_id="pay_concurrent",
                merchant_id="acc_test",
            )
            session.commit()
            return result.payment_case.id, result.created

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _value: create_case(), range(2)))

    assert outcomes[0][0] == outcomes[1][0]
    assert sum(created for _case_id, created in outcomes) == 1
    with integration_session_factory() as session:
        count = session.scalar(select(func.count()).select_from(PaymentCase))
    assert count == 1


def test_refunded_payment_uses_safe_non_recovery_terminal(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_refunded"] = payment_snapshot(
        payment_id="pay_refunded",
        status="refunded",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_refunded",
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    payment_case = load_cases(integration_session_factory)[0]
    assert result.reason_code == "PAYMENT_REFUNDED"
    assert payment_case.current_state is CaseState.EXHAUSTED
    assert payment_case.razorpay_payment_status == "refunded"
    assert payment_case.resolved_at is not None


@pytest.mark.parametrize("external_status", ["created", "authorized"])
def test_nonfinal_payment_state_does_not_advance_recovery(
    integration_session_factory: SessionFactory,
    external_status: str,
) -> None:
    payment_id = f"pay_{external_status}"
    client = StubRazorpayClient()
    client.payments[payment_id] = payment_snapshot(
        payment_id=payment_id,
        status=external_status,
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id=payment_id,
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    payment_case = load_cases(integration_session_factory)[0]
    assert result.reason_code == "PAYMENT_STATE_NOT_RECOVERY_READY"
    assert payment_case.current_state is CaseState.RECONCILING
    assert payment_case.attempt_count == 0
    assert payment_case.current_state is not CaseState.DIAGNOSED
    assert load_event(
        integration_session_factory,
        event_id,
    ).processing_status is EventProcessingStatus.PROCESSED

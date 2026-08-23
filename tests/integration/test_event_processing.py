"""PostgreSQL tests for the stored-event processing lifecycle."""

from sqlalchemy import func, select

from arc.domain.enums import EventProcessingStatus
from arc.domain.models import CaseEvent, PaymentCase
from arc.integrations.razorpay import (
    RazorpayAuthenticationError,
    RazorpayUnavailableError,
)
from tests.reconciliation_support import (
    SessionFactory,
    StubRazorpayClient,
    load_event,
    payment_snapshot,
    processor,
    store_event,
)


def test_event_moves_received_to_processing_then_processed(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_lifecycle"] = payment_snapshot(
        payment_id="pay_lifecycle",
        status="failed",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_lifecycle",
    )
    observed_statuses: list[EventProcessingStatus] = []

    def observe_claimed_state() -> None:
        observed_statuses.append(
            load_event(
                integration_session_factory,
                event_id,
            ).processing_status
        )

    client.on_fetch = observe_claimed_state
    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    stored = load_event(integration_session_factory, event_id)
    assert observed_statuses == [EventProcessingStatus.PROCESSING]
    assert result.processing_status is EventProcessingStatus.PROCESSED
    assert stored.processing_status is EventProcessingStatus.PROCESSED
    assert stored.processed_at is not None
    assert stored.processing_error is None


def test_api_unavailable_marks_event_failed_with_sanitized_error(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_unavailable"] = RazorpayUnavailableError(
        "Razorpay read API is temporarily unavailable"
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_unavailable",
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    stored = load_event(integration_session_factory, event_id)
    assert result.processing_status is EventProcessingStatus.FAILED
    assert stored.processing_status is EventProcessingStatus.FAILED
    assert stored.processed_at is not None
    assert stored.processing_error == "Razorpay read API is temporarily unavailable"
    assert "Authorization" not in stored.processing_error
    assert "payload" not in stored.processing_error


def test_authentication_failure_never_persists_credentials(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_auth_failure"] = RazorpayAuthenticationError(
        "Razorpay read API authentication failed"
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_auth_failure",
    )

    processor(integration_session_factory, client).process_webhook_event(event_id)

    stored_error = load_event(
        integration_session_factory,
        event_id,
    ).processing_error
    assert stored_error == "Razorpay read API authentication failed"
    assert "rzp_" not in stored_error
    assert ":" not in stored_error


def test_processed_event_is_idempotent_and_not_refetched(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_processed"] = payment_snapshot(
        payment_id="pay_processed",
        status="captured",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.captured",
        payment_id="pay_processed",
    )
    service = processor(integration_session_factory, client)

    first = service.process_webhook_event(event_id)
    second = service.process_webhook_event(event_id)

    assert first.processing_status is EventProcessingStatus.PROCESSED
    assert second.processing_status is EventProcessingStatus.PROCESSED
    assert second.idempotent is True
    assert client.calls == [("payment", "pay_processed")]


def test_unsupported_event_is_not_reconciled(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    event_id = store_event(
        integration_session_factory,
        event_type="refund.failed",
        payment_id="pay_unsupported",
        processing_status=EventProcessingStatus.UNSUPPORTED,
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    assert result.processing_status is EventProcessingStatus.UNSUPPORTED
    assert result.idempotent is True
    assert client.calls == []
    with integration_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PaymentCase)) == 0
        assert session.scalar(select(func.count()).select_from(CaseEvent)) == 0


def test_failed_reconciliation_never_creates_case_or_action_state(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_no_action"] = RazorpayUnavailableError(
        "Razorpay read API is temporarily unavailable"
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_no_action",
    )

    processor(integration_session_factory, client).process_webhook_event(event_id)

    with integration_session_factory() as session:
        assert session.scalar(select(func.count()).select_from(PaymentCase)) == 0
        assert session.scalar(select(func.count()).select_from(CaseEvent)) == 0


def test_missing_required_identifier_fails_safely_without_external_call(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id=None,
    )

    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    stored = load_event(integration_session_factory, event_id)
    assert result.processing_status is EventProcessingStatus.FAILED
    assert stored.processing_error == "Payment webhook is missing a payment identifier"
    assert client.calls == []

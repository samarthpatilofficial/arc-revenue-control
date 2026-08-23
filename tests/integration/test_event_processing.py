"""PostgreSQL tests for the stored-event processing lifecycle."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from sqlalchemy import func, select

from arc.domain.enums import CaseState, EventProcessingStatus
from arc.domain.models import CaseEvent, PaymentCase
from arc.integrations.razorpay import (
    RazorpayAuthenticationError,
    RazorpayUnavailableError,
)
from arc.reconciliation.service import (
    PROCESSING_LEASE_SECONDS,
    WebhookProcessingResult,
)
from tests.reconciliation_support import (
    SessionFactory,
    StubRazorpayClient,
    load_cases,
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
    observed_claims: list[
        tuple[EventProcessingStatus, datetime | None, int]
    ] = []

    def observe_claimed_state() -> None:
        claimed_event = load_event(integration_session_factory, event_id)
        observed_claims.append(
            (
                claimed_event.processing_status,
                claimed_event.processing_started_at,
                claimed_event.processing_attempt_count,
            )
        )

    client.on_fetch = observe_claimed_state
    result = processor(
        integration_session_factory,
        client,
    ).process_webhook_event(event_id)

    stored = load_event(integration_session_factory, event_id)
    assert len(observed_claims) == 1
    observed_status, observed_started_at, observed_attempt_count = (
        observed_claims[0]
    )
    assert observed_status is EventProcessingStatus.PROCESSING
    assert observed_started_at is not None
    assert observed_started_at.utcoffset() is not None
    assert observed_attempt_count == 1
    assert result.processing_status is EventProcessingStatus.PROCESSED
    assert stored.processing_status is EventProcessingStatus.PROCESSED
    assert stored.processing_started_at == observed_started_at
    assert stored.processing_attempt_count == 1
    assert stored.processed_at is not None
    assert stored.processing_error is None


def test_fresh_processing_lease_is_not_reclaimed(
    integration_session_factory: SessionFactory,
) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    started_at = now - timedelta(seconds=PROCESSING_LEASE_SECONDS - 1)
    client = StubRazorpayClient()
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_fresh_lease",
        processing_status=EventProcessingStatus.PROCESSING,
        processing_started_at=started_at,
        processing_attempt_count=1,
        processing_error="existing worker still owns this attempt",
    )

    result = processor(
        integration_session_factory,
        client,
        clock=lambda: now,
    ).process_webhook_event(event_id)

    stored = load_event(integration_session_factory, event_id)
    assert result.reason_code == "EVENT_ALREADY_PROCESSING"
    assert result.idempotent is True
    assert stored.processing_status is EventProcessingStatus.PROCESSING
    assert stored.processing_started_at == started_at
    assert stored.processing_attempt_count == 1
    assert client.calls == []


def test_stale_processing_lease_is_reclaimed_and_completed(
    integration_session_factory: SessionFactory,
) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    stale_started_at = now - timedelta(
        seconds=PROCESSING_LEASE_SECONDS + 1
    )
    client = StubRazorpayClient()
    client.payments["pay_stale_lease"] = payment_snapshot(
        payment_id="pay_stale_lease",
        status="failed",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_stale_lease",
        processing_status=EventProcessingStatus.PROCESSING,
        processing_started_at=stale_started_at,
        processing_attempt_count=1,
        processing_error="abandoned attempt",
    )
    observed_claims: list[tuple[datetime | None, int, str | None]] = []

    def observe_reclaimed_state() -> None:
        claimed_event = load_event(integration_session_factory, event_id)
        observed_claims.append(
            (
                claimed_event.processing_started_at,
                claimed_event.processing_attempt_count,
                claimed_event.processing_error,
            )
        )

    client.on_fetch = observe_reclaimed_state
    result = processor(
        integration_session_factory,
        client,
        clock=lambda: now,
    ).process_webhook_event(event_id)

    stored = load_event(integration_session_factory, event_id)
    assert observed_claims == [(now, 2, None)]
    assert result.processing_status is EventProcessingStatus.PROCESSED
    assert stored.processing_status is EventProcessingStatus.PROCESSED
    assert stored.processing_started_at == now
    assert stored.processing_attempt_count == 2
    assert stored.processed_at == now
    assert stored.processing_error is None
    assert len(load_cases(integration_session_factory)) == 1


def test_processing_event_without_lease_timestamp_is_reclaimed(
    integration_session_factory: SessionFactory,
) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    client = StubRazorpayClient()
    client.payments["pay_missing_lease"] = payment_snapshot(
        payment_id="pay_missing_lease",
        status="failed",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_missing_lease",
        processing_status=EventProcessingStatus.PROCESSING,
        processing_started_at=None,
        processing_attempt_count=1,
    )

    result = processor(
        integration_session_factory,
        client,
        clock=lambda: now,
    ).process_webhook_event(event_id)

    stored = load_event(integration_session_factory, event_id)
    assert result.processing_status is EventProcessingStatus.PROCESSED
    assert stored.processing_started_at == now
    assert stored.processing_attempt_count == 2


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
    assert stored.processing_started_at is not None
    assert stored.processing_attempt_count == 1
    assert stored.processed_at is not None
    assert stored.processing_error == "Razorpay read API is temporarily unavailable"
    assert "Authorization" not in stored.processing_error
    assert "payload" not in stored.processing_error


def test_failed_event_is_retryable_and_increments_attempt_count(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.payments["pay_retry"] = RazorpayUnavailableError(
        "Razorpay read API is temporarily unavailable"
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_retry",
    )
    service = processor(integration_session_factory, client)

    first = service.process_webhook_event(event_id)
    failed_event = load_event(integration_session_factory, event_id)
    assert first.processing_status is EventProcessingStatus.FAILED
    assert failed_event.processing_attempt_count == 1
    assert failed_event.processing_error is not None

    client.payments["pay_retry"] = payment_snapshot(
        payment_id="pay_retry",
        status="failed",
    )
    retry_claims: list[tuple[EventProcessingStatus, int, str | None]] = []

    def observe_retry_claim() -> None:
        claimed_event = load_event(integration_session_factory, event_id)
        retry_claims.append(
            (
                claimed_event.processing_status,
                claimed_event.processing_attempt_count,
                claimed_event.processing_error,
            )
        )

    client.on_fetch = observe_retry_claim
    second = service.process_webhook_event(event_id)

    retried_event = load_event(integration_session_factory, event_id)
    assert retry_claims == [(EventProcessingStatus.PROCESSING, 2, None)]
    assert second.processing_status is EventProcessingStatus.PROCESSED
    assert retried_event.processing_status is EventProcessingStatus.PROCESSED
    assert retried_event.processing_attempt_count == 2
    assert retried_event.processing_error is None


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


def test_reclaimed_processing_does_not_regress_terminal_payment_case(
    integration_session_factory: SessionFactory,
) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    client = StubRazorpayClient()
    client.payments["pay_terminal_reclaim"] = payment_snapshot(
        payment_id="pay_terminal_reclaim",
        status="captured",
    )
    initial_event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_terminal_reclaim",
    )
    service = processor(integration_session_factory, client)
    service.process_webhook_event(initial_event_id)
    assert (
        load_cases(integration_session_factory)[0].current_state
        is CaseState.RECOVERED
    )

    reclaimed_event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_terminal_reclaim",
        processing_status=EventProcessingStatus.PROCESSING,
        processing_started_at=now - timedelta(
            seconds=PROCESSING_LEASE_SECONDS + 1
        ),
        processing_attempt_count=1,
    )

    result = processor(
        integration_session_factory,
        client,
        clock=lambda: now,
    ).process_webhook_event(reclaimed_event_id)

    payment_case = load_cases(integration_session_factory)[0]
    reclaimed_event = load_event(
        integration_session_factory,
        reclaimed_event_id,
    )
    assert result.processing_status is EventProcessingStatus.PROCESSED
    assert reclaimed_event.processing_attempt_count == 2
    assert payment_case.current_state is CaseState.RECOVERED
    assert payment_case.razorpay_payment_status == "captured"


def test_concurrent_stale_reclaim_allows_only_one_processing_attempt(
    integration_session_factory: SessionFactory,
) -> None:
    now = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    client = StubRazorpayClient()
    client.payments["pay_concurrent_reclaim"] = payment_snapshot(
        payment_id="pay_concurrent_reclaim",
        status="failed",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_concurrent_reclaim",
        processing_status=EventProcessingStatus.PROCESSING,
        processing_started_at=now - timedelta(
            seconds=PROCESSING_LEASE_SECONDS + 1
        ),
        processing_attempt_count=1,
    )
    service = processor(
        integration_session_factory,
        client,
        clock=lambda: now,
    )
    start_together = Barrier(2)

    def process_concurrently() -> WebhookProcessingResult:
        start_together.wait(timeout=5)
        return service.process_webhook_event(event_id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _value: process_concurrently(), range(2)))

    stored = load_event(integration_session_factory, event_id)
    assert len(client.calls) == 1
    assert sum(not result.idempotent for result in results) == 1
    assert stored.processing_status is EventProcessingStatus.PROCESSED
    assert stored.processing_attempt_count == 2


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

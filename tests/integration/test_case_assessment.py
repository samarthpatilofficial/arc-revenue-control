"""PostgreSQL tests for transactional deterministic case assessment."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

from sqlalchemy import select

from arc.assessment import CaseAssessmentResult
from arc.domain.enums import (
    CaseState,
    EligibilityDecision,
    FailureCategory,
    RecoveryDisposition,
)
from arc.domain.models import PaymentCase
from arc.policy import RECONCILIATION_FRESHNESS_SECONDS
from tests.reconciliation_support import (
    SessionFactory,
    StubRazorpayClient,
    assessor,
    load_case_events,
    load_cases,
    payment_snapshot,
    processor,
    store_event,
    subscription_snapshot,
)


def _clock_after_reconciliation(payment_case: PaymentCase) -> datetime:
    assert payment_case.last_reconciled_at is not None
    return payment_case.last_reconciled_at + timedelta(seconds=1)


def _reconcile_payment(
    session_factory: SessionFactory,
    client: StubRazorpayClient,
    *,
    payment_id: str,
    error_reason: str | None = "incorrect_otp",
    error_source: str | None = "customer",
    error_step: str | None = "payment_authentication",
    method: str | None = "card",
) -> PaymentCase:
    client.payments[payment_id] = payment_snapshot(
        payment_id=payment_id,
        status="failed",
        method=method,
        error_reason=error_reason,
        error_source=error_source,
        error_step=error_step,
    )
    event_id = store_event(
        session_factory,
        event_type="payment.failed",
        payment_id=payment_id,
    )
    processor(session_factory, client).process_webhook_event(event_id)
    return load_cases(session_factory)[0]


def test_eligible_payment_persists_assessment_method_and_audit_once(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    payment_case = _reconcile_payment(
        integration_session_factory,
        client,
        payment_id="pay_assessment_projection",
        method="card",
    )
    assessed_at = _clock_after_reconciliation(payment_case)

    result = assessor(
        integration_session_factory,
        clock=lambda: assessed_at,
    ).assess_case(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    assert result.idempotent is False
    assert result.case_state is CaseState.DIAGNOSED
    assert stored.current_state is CaseState.DIAGNOSED
    assert stored.razorpay_payment_method == "card"
    assert stored.eligibility_status is EligibilityDecision.ELIGIBLE
    assert stored.eligibility_reason_code == "PAYMENT_FAILURE_CONFIRMED"
    assert stored.eligibility_evaluated_at == assessed_at
    assert stored.failure_category is FailureCategory.CUSTOMER_AUTHENTICATION
    assert (
        stored.recovery_disposition
        is RecoveryDisposition.CUSTOMER_ACTION_REQUIRED
    )
    assert stored.diagnosis_reason_code == "STRUCTURED_REASON_INCORRECT_OTP"
    assert stored.diagnosed_at == assessed_at
    assert stored.assessment_fingerprint is not None
    assert len(stored.assessment_fingerprint) == 64

    audit_types = [
        event.event_type
        for event in load_case_events(
            integration_session_factory,
            payment_case.id,
        )
    ]
    assert audit_types.count("ELIGIBILITY_EVALUATED") == 1
    assert audit_types.count("FAILURE_DIAGNOSED") == 1
    assert audit_types.count("FAILURE_REDIAGNOSED") == 0


def test_repeated_assessment_is_idempotent_without_duplicate_audit(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    payment_case = _reconcile_payment(
        integration_session_factory,
        client,
        payment_id="pay_assessment_idempotent",
    )
    assessed_at = _clock_after_reconciliation(payment_case)
    service = assessor(
        integration_session_factory,
        clock=lambda: assessed_at,
    )

    first = service.assess_case(payment_case.id)
    first_events = load_case_events(
        integration_session_factory,
        payment_case.id,
    )
    second = service.assess_case(payment_case.id)
    second_events = load_case_events(
        integration_session_factory,
        payment_case.id,
    )

    assert first.idempotent is False
    assert second.idempotent is True
    assert first.assessment_fingerprint == second.assessment_fingerprint
    assert first.case_state is second.case_state is CaseState.DIAGNOSED
    assert len(second_events) == len(first_events)


def test_concurrent_assessment_does_not_duplicate_audit_events(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    payment_case = _reconcile_payment(
        integration_session_factory,
        client,
        payment_id="pay_assessment_concurrent",
    )
    assessed_at = _clock_after_reconciliation(payment_case)
    service = assessor(
        integration_session_factory,
        clock=lambda: assessed_at,
    )
    start_together = Barrier(2)

    def run_assessment() -> CaseAssessmentResult:
        start_together.wait(timeout=5)
        return service.assess_case(payment_case.id)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _value: run_assessment(), range(2)))

    audit_types = [
        event.event_type
        for event in load_case_events(
            integration_session_factory,
            payment_case.id,
        )
    ]
    assert sum(result.idempotent for result in results) == 1
    assert audit_types.count("ELIGIBILITY_EVALUATED") == 1
    assert audit_types.count("FAILURE_DIAGNOSED") == 1


def test_new_reconciliation_fingerprint_refreshes_diagnosis_without_regression(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    payment_case = _reconcile_payment(
        integration_session_factory,
        client,
        payment_id="pay_assessment_refresh",
    )
    first_clock = _clock_after_reconciliation(payment_case)
    first = assessor(
        integration_session_factory,
        clock=lambda: first_clock,
    ).assess_case(payment_case.id)

    client.payments["pay_assessment_refresh"] = payment_snapshot(
        payment_id="pay_assessment_refresh",
        status="failed",
        error_reason="bank_technical_error",
        error_source="customer",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="payment.failed",
        payment_id="pay_assessment_refresh",
    )
    processor(integration_session_factory, client).process_webhook_event(event_id)
    reconciled_again = load_cases(integration_session_factory)[0]
    second_clock = _clock_after_reconciliation(reconciled_again)

    second = assessor(
        integration_session_factory,
        clock=lambda: second_clock,
    ).assess_case(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    audit_types = [
        event.event_type
        for event in load_case_events(
            integration_session_factory,
            payment_case.id,
        )
    ]
    assert first.assessment_fingerprint != second.assessment_fingerprint
    assert second.idempotent is False
    assert stored.current_state is CaseState.DIAGNOSED
    assert stored.failure_category is FailureCategory.BANK_OR_ISSUER
    assert stored.recovery_disposition is RecoveryDisposition.RETRY_LATER
    assert audit_types.count("ELIGIBILITY_EVALUATED") == 2
    assert audit_types.count("FAILURE_DIAGNOSED") == 1
    assert audit_types.count("FAILURE_REDIAGNOSED") == 1


def test_newly_captured_terminal_case_cannot_regress_during_assessment(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    payment_case = _reconcile_payment(
        integration_session_factory,
        client,
        payment_id="pay_assessment_captured",
    )
    first_clock = _clock_after_reconciliation(payment_case)
    assessor(
        integration_session_factory,
        clock=lambda: first_clock,
    ).assess_case(payment_case.id)

    client.payments["pay_assessment_captured"] = payment_snapshot(
        payment_id="pay_assessment_captured",
        status="captured",
    )
    captured_event_id = store_event(
        integration_session_factory,
        event_type="payment.captured",
        payment_id="pay_assessment_captured",
    )
    processor(integration_session_factory, client).process_webhook_event(
        captured_event_id
    )
    captured_case = load_cases(integration_session_factory)[0]
    second_clock = _clock_after_reconciliation(captured_case)

    result = assessor(
        integration_session_factory,
        clock=lambda: second_clock,
    ).assess_case(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    assert result.eligibility_status is EligibilityDecision.STOP
    assert result.eligibility_reason_code == "STOP_ALREADY_RECOVERED"
    assert stored.current_state is CaseState.RECOVERED
    assert stored.failure_category is None
    assert stored.recovery_disposition is None
    assert stored.diagnosed_at is None


def test_pending_subscription_never_becomes_diagnosed(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.subscriptions["sub_assessment_pending"] = subscription_snapshot(
        subscription_id="sub_assessment_pending",
        status="pending",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="subscription.pending",
        subscription_id="sub_assessment_pending",
    )
    processor(integration_session_factory, client).process_webhook_event(event_id)
    payment_case = load_cases(integration_session_factory)[0]
    assessed_at = _clock_after_reconciliation(payment_case)

    result = assessor(
        integration_session_factory,
        clock=lambda: assessed_at,
    ).assess_case(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    assert result.eligibility_status is EligibilityDecision.WAIT
    assert result.eligibility_reason_code == "PLATFORM_RETRY_ACTIVE"
    assert stored.current_state is CaseState.RECONCILING
    assert stored.failure_category is None
    assert "FAILURE_DIAGNOSED" not in {
        event.event_type
        for event in load_case_events(
            integration_session_factory,
            payment_case.id,
        )
    }


def test_halted_subscription_becomes_diagnosed(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    client.subscriptions["sub_assessment_halted"] = subscription_snapshot(
        subscription_id="sub_assessment_halted",
        status="halted",
    )
    event_id = store_event(
        integration_session_factory,
        event_type="subscription.halted",
        subscription_id="sub_assessment_halted",
    )
    processor(integration_session_factory, client).process_webhook_event(event_id)
    payment_case = load_cases(integration_session_factory)[0]
    assessed_at = _clock_after_reconciliation(payment_case)

    assessor(
        integration_session_factory,
        clock=lambda: assessed_at,
    ).assess_case(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    assert stored.current_state is CaseState.DIAGNOSED
    assert (
        stored.failure_category
        is FailureCategory.SUBSCRIPTION_RETRY_EXHAUSTED
    )
    assert (
        stored.recovery_disposition
        is RecoveryDisposition.RECOVERY_STRATEGY_REQUIRED
    )
    assert (
        stored.diagnosis_reason_code
        == "SUBSCRIPTION_AUTOMATIC_RETRIES_EXHAUSTED"
    )


def test_stale_reconciliation_never_becomes_diagnosed(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    payment_case = _reconcile_payment(
        integration_session_factory,
        client,
        payment_id="pay_assessment_stale",
    )
    assessed_at = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    stale_at = assessed_at - timedelta(
        seconds=RECONCILIATION_FRESHNESS_SECONDS + 1
    )
    with integration_session_factory() as session:
        stored = session.scalar(
            select(PaymentCase).where(PaymentCase.id == payment_case.id)
        )
        assert stored is not None
        stored.last_reconciled_at = stale_at
        session.commit()

    result = assessor(
        integration_session_factory,
        clock=lambda: assessed_at,
    ).assess_case(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    assert result.eligibility_status is EligibilityDecision.WAIT
    assert result.eligibility_reason_code == "RECONCILIATION_STALE"
    assert stored.current_state is CaseState.RECONCILING
    assert stored.failure_category is None


def test_unknown_diagnosis_remains_bounded_and_safe(
    integration_session_factory: SessionFactory,
) -> None:
    client = StubRazorpayClient()
    payment_case = _reconcile_payment(
        integration_session_factory,
        client,
        payment_id="pay_assessment_unknown",
        error_reason="future_reason",
        error_source=None,
        error_step=None,
    )
    assessed_at = _clock_after_reconciliation(payment_case)

    assessor(
        integration_session_factory,
        clock=lambda: assessed_at,
    ).assess_case(payment_case.id)

    stored = load_cases(integration_session_factory)[0]
    diagnosis_audit = next(
        event
        for event in load_case_events(
            integration_session_factory,
            payment_case.id,
        )
        if event.event_type == "FAILURE_DIAGNOSED"
    )
    assert stored.current_state is CaseState.DIAGNOSED
    assert stored.failure_category is FailureCategory.UNKNOWN
    assert stored.recovery_disposition is RecoveryDisposition.MANUAL_REVIEW
    assert stored.diagnosis_reason_code == "PAYMENT_FAILURE_UNCLASSIFIED"
    assert "error_description" not in diagnosis_audit.event_data["evidence"]
    assert "payload" not in diagnosis_audit.event_data

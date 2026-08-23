"""Unit tests for the deterministic recovery preconditions gate."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from arc.domain.enums import CaseState, EligibilityDecision
from arc.domain.models import PaymentCase
from arc.policy import (
    RECONCILIATION_FRESHNESS_SECONDS,
    EligibilityResult,
    assess_eligibility,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _payment_case(
    *,
    state: CaseState = CaseState.RECONCILING,
    status: str = "failed",
    reconciled_at: datetime | None = NOW,
    payment_id: str | None = "pay_unit",
) -> PaymentCase:
    return PaymentCase(
        id=uuid4(),
        case_reference=f"pay_{uuid4().hex}",
        merchant_id="merchant_unit",
        payment_id=payment_id,
        razorpay_payment_status=status,
        current_state=state,
        last_reconciled_at=reconciled_at,
    )


def _subscription_case(
    *,
    status: str,
    state: CaseState = CaseState.RECONCILING,
) -> PaymentCase:
    return PaymentCase(
        id=uuid4(),
        case_reference=f"sub_{uuid4().hex}",
        merchant_id="merchant_unit",
        subscription_id="sub_unit",
        razorpay_subscription_status=status,
        current_state=state,
        last_reconciled_at=NOW,
    )


def _assess(payment_case: PaymentCase) -> EligibilityResult:
    return assess_eligibility(payment_case, clock=lambda: NOW)


@pytest.mark.parametrize(
    ("state", "reason_code"),
    [
        (CaseState.RECOVERED, "STOP_ALREADY_RECOVERED"),
        (CaseState.EXHAUSTED, "STOP_ALREADY_EXHAUSTED"),
        (CaseState.ESCALATED, "STOP_ALREADY_ESCALATED"),
    ],
)
def test_terminal_case_stops_without_reopening(
    state: CaseState,
    reason_code: str,
) -> None:
    result = _assess(_payment_case(state=state))

    assert result.decision is EligibilityDecision.STOP
    assert result.reason_code == reason_code


def test_missing_reconciliation_waits() -> None:
    result = _assess(_payment_case(reconciled_at=None))

    assert result.decision is EligibilityDecision.WAIT
    assert result.reason_code == "RECONCILIATION_REQUIRED"


def test_stale_reconciliation_waits() -> None:
    stale_at = NOW - timedelta(seconds=RECONCILIATION_FRESHNESS_SECONDS + 1)
    result = _assess(_payment_case(reconciled_at=stale_at))

    assert result.decision is EligibilityDecision.WAIT
    assert result.reason_code == "RECONCILIATION_STALE"


@pytest.mark.parametrize(
    ("status", "decision", "reason_code"),
    [
        (
            "failed",
            EligibilityDecision.ELIGIBLE,
            "PAYMENT_FAILURE_CONFIRMED",
        ),
        (
            "captured",
            EligibilityDecision.STOP,
            "PAYMENT_ALREADY_CAPTURED",
        ),
        ("refunded", EligibilityDecision.STOP, "PAYMENT_REFUNDED"),
        ("authorized", EligibilityDecision.WAIT, "PAYMENT_NOT_FINAL"),
        ("created", EligibilityDecision.WAIT, "PAYMENT_NOT_FINAL"),
        (
            "future_status",
            EligibilityDecision.REVIEW,
            "UNRECOGNIZED_PAYMENT_STATUS",
        ),
    ],
)
def test_payment_status_rules(
    status: str,
    decision: EligibilityDecision,
    reason_code: str,
) -> None:
    result = _assess(_payment_case(status=status))

    assert result.decision is decision
    assert result.reason_code == reason_code


def test_failed_payment_without_optional_reason_remains_eligible() -> None:
    payment_case = _payment_case(status="failed")
    payment_case.error_reason = None

    result = _assess(payment_case)

    assert result.decision is EligibilityDecision.ELIGIBLE


@pytest.mark.parametrize(
    ("status", "decision", "reason_code"),
    [
        ("pending", EligibilityDecision.WAIT, "PLATFORM_RETRY_ACTIVE"),
        (
            "halted",
            EligibilityDecision.ELIGIBLE,
            "SUBSCRIPTION_RETRIES_EXHAUSTED",
        ),
        ("active", EligibilityDecision.STOP, "SUBSCRIPTION_ACTIVE"),
        ("paused", EligibilityDecision.WAIT, "SUBSCRIPTION_PAUSED"),
        (
            "created",
            EligibilityDecision.WAIT,
            "SUBSCRIPTION_NOT_RECOVERY_READY",
        ),
        (
            "authenticated",
            EligibilityDecision.WAIT,
            "SUBSCRIPTION_NOT_RECOVERY_READY",
        ),
        (
            "cancelled",
            EligibilityDecision.STOP,
            "SUBSCRIPTION_TERMINAL",
        ),
        (
            "completed",
            EligibilityDecision.STOP,
            "SUBSCRIPTION_TERMINAL",
        ),
        ("expired", EligibilityDecision.STOP, "SUBSCRIPTION_TERMINAL"),
        (
            "future_status",
            EligibilityDecision.REVIEW,
            "UNRECOGNIZED_SUBSCRIPTION_STATUS",
        ),
    ],
)
def test_subscription_status_rules(
    status: str,
    decision: EligibilityDecision,
    reason_code: str,
) -> None:
    result = _assess(_subscription_case(status=status))

    assert result.decision is decision
    assert result.reason_code == reason_code


def test_incomplete_identity_requires_review() -> None:
    payment_case = _payment_case(payment_id=None)

    result = _assess(payment_case)

    assert result.decision is EligibilityDecision.REVIEW
    assert result.reason_code == "CASE_IDENTITY_MISSING"


def test_conflicting_external_statuses_require_review() -> None:
    payment_case = _payment_case()
    payment_case.subscription_id = "sub_conflict"
    payment_case.razorpay_subscription_status = "halted"

    result = _assess(payment_case)

    assert result.decision is EligibilityDecision.REVIEW
    assert result.reason_code == "CONFLICTING_EXTERNAL_STATUSES"


def test_reconciled_case_without_external_status_requires_review() -> None:
    payment_case = _payment_case(status="failed")
    payment_case.razorpay_payment_status = None

    result = _assess(payment_case)

    assert result.decision is EligibilityDecision.REVIEW
    assert result.reason_code == "AUTHORITATIVE_STATUS_MISSING"


def test_fingerprint_ignores_mutable_assessment_outputs() -> None:
    payment_case = _payment_case()
    first = _assess(payment_case).assessment_fingerprint
    payment_case.eligibility_reason_code = "OLD_OUTPUT"
    payment_case.diagnosis_reason_code = "OLD_DIAGNOSIS"

    second = _assess(payment_case).assessment_fingerprint

    assert first == second

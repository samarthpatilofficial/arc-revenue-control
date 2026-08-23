"""Unit tests for structured deterministic failure intelligence."""

from uuid import uuid4

import pytest

from arc.diagnosis import classify_failure
from arc.domain.enums import FailureCategory, RecoveryDisposition
from arc.domain.models import PaymentCase


def _payment_failure(
    *,
    error_reason: str | None = None,
    error_source: str | None = None,
    error_step: str | None = None,
    error_description: str | None = None,
) -> PaymentCase:
    return PaymentCase(
        id=uuid4(),
        case_reference=f"pay_{uuid4().hex}",
        merchant_id="merchant_unit",
        payment_id="pay_unit",
        razorpay_payment_status="failed",
        razorpay_payment_method="card",
        error_reason=error_reason,
        error_source=error_source,
        error_step=error_step,
        error_description=error_description,
    )


@pytest.mark.parametrize(
    ("reason", "category", "disposition"),
    [
        (
            "incorrect_otp",
            FailureCategory.CUSTOMER_AUTHENTICATION,
            RecoveryDisposition.CUSTOMER_ACTION_REQUIRED,
        ),
        (
            "insufficient_funds",
            FailureCategory.CUSTOMER_FUNDS,
            RecoveryDisposition.CUSTOMER_ACTION_REQUIRED,
        ),
        (
            "payment_cancelled",
            FailureCategory.CUSTOMER_INTERRUPTION,
            RecoveryDisposition.CUSTOMER_ACTION_REQUIRED,
        ),
        (
            "transaction_limit_exceeded",
            FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
            RecoveryDisposition.ALTERNATE_METHOD_PREFERRED,
        ),
        (
            "bank_technical_error",
            FailureCategory.BANK_OR_ISSUER,
            RecoveryDisposition.RETRY_LATER,
        ),
        (
            "gateway_technical_error",
            FailureCategory.GATEWAY_OR_NETWORK,
            RecoveryDisposition.RETRY_LATER,
        ),
    ],
)
def test_exact_structured_reason_rules(
    reason: str,
    category: FailureCategory,
    disposition: RecoveryDisposition,
) -> None:
    result = classify_failure(_payment_failure(error_reason=reason))

    assert result.failure_category is category
    assert result.recovery_disposition is disposition


@pytest.mark.parametrize(
    ("source", "category", "disposition"),
    [
        (
            "customer",
            FailureCategory.UNKNOWN,
            RecoveryDisposition.MANUAL_REVIEW,
        ),
        (
            "business",
            FailureCategory.MERCHANT_CONFIGURATION,
            RecoveryDisposition.MERCHANT_FIX_REQUIRED,
        ),
        (
            "gateway",
            FailureCategory.GATEWAY_OR_NETWORK,
            RecoveryDisposition.RETRY_LATER,
        ),
    ],
)
def test_unmapped_reason_uses_structured_source_fallback(
    source: str,
    category: FailureCategory,
    disposition: RecoveryDisposition,
) -> None:
    result = classify_failure(
        _payment_failure(
            error_reason="new_future_reason",
            error_source=source,
        )
    )

    assert result.failure_category is category
    assert result.recovery_disposition is disposition


def test_exact_reason_has_precedence_over_conflicting_source() -> None:
    result = classify_failure(
        _payment_failure(
            error_reason="bank_technical_error",
            error_source="customer",
        )
    )

    assert result.failure_category is FailureCategory.BANK_OR_ISSUER


def test_structured_step_is_used_after_unmapped_source() -> None:
    result = classify_failure(
        _payment_failure(error_step="payment_authentication")
    )

    assert result.failure_category is FailureCategory.CUSTOMER_AUTHENTICATION


def test_unknown_evidence_is_bounded_manual_review() -> None:
    result = classify_failure(_payment_failure())

    assert result.failure_category is FailureCategory.UNKNOWN
    assert result.recovery_disposition is RecoveryDisposition.MANUAL_REVIEW
    assert result.diagnosis_reason_code == "PAYMENT_FAILURE_UNCLASSIFIED"


def test_error_description_is_not_used_for_machine_classification() -> None:
    result = classify_failure(
        _payment_failure(error_description="insufficient funds")
    )

    assert result.failure_category is FailureCategory.UNKNOWN
    assert "error_description" not in result.evidence


def test_halted_subscription_has_deterministic_diagnosis() -> None:
    payment_case = PaymentCase(
        id=uuid4(),
        case_reference=f"sub_{uuid4().hex}",
        merchant_id="merchant_unit",
        subscription_id="sub_unit",
        razorpay_subscription_status="halted",
    )

    result = classify_failure(payment_case)

    assert (
        result.failure_category
        is FailureCategory.SUBSCRIPTION_RETRY_EXHAUSTED
    )
    assert (
        result.recovery_disposition
        is RecoveryDisposition.RECOVERY_STRATEGY_REQUIRED
    )
    assert (
        result.diagnosis_reason_code
        == "SUBSCRIPTION_AUTOMATIC_RETRIES_EXHAUSTED"
    )

"""Minimum-data strategy context built from validated deterministic truth."""

from collections.abc import Callable
from datetime import datetime

from arc.diagnosis import classify_failure
from arc.domain.enums import EligibilityDecision
from arc.domain.models import PaymentCase
from arc.intelligence.errors import StrategyNotAllowedError
from arc.intelligence.schemas import StrategyContext
from arc.policy import assess_eligibility


def required_assessment_fingerprint(payment_case: PaymentCase) -> str:
    """Return the persisted deterministic assessment fingerprint."""

    fingerprint = payment_case.assessment_fingerprint
    if fingerprint is None:
        raise StrategyNotAllowedError(
            "Current deterministic assessment is missing"
        )
    return fingerprint


def validate_strategy_context(
    payment_case: PaymentCase,
    *,
    clock: Callable[[], datetime],
) -> StrategyContext:
    """Recheck eligibility and diagnosis, then build the bounded AI context."""

    eligibility = assess_eligibility(payment_case, clock=clock)
    if eligibility.decision is not EligibilityDecision.ELIGIBLE:
        raise StrategyNotAllowedError(
            "Current deterministic eligibility does not allow strategy"
        )
    if (
        payment_case.eligibility_status is not EligibilityDecision.ELIGIBLE
        or payment_case.eligibility_reason_code != eligibility.reason_code
        or payment_case.assessment_fingerprint
        != eligibility.assessment_fingerprint
        or payment_case.eligibility_evaluated_at is None
        or payment_case.failure_category is None
        or payment_case.recovery_disposition is None
        or payment_case.diagnosis_reason_code is None
        or payment_case.diagnosed_at is None
    ):
        raise StrategyNotAllowedError(
            "Current deterministic assessment is missing or stale"
        )

    diagnosis = classify_failure(payment_case)
    if (
        diagnosis.failure_category is not payment_case.failure_category
        or diagnosis.recovery_disposition
        is not payment_case.recovery_disposition
        or diagnosis.diagnosis_reason_code
        != payment_case.diagnosis_reason_code
    ):
        raise StrategyNotAllowedError(
            "Current deterministic diagnosis is missing or stale"
        )
    try:
        return _build_strategy_context(payment_case)
    except ValueError as error:
        raise StrategyNotAllowedError(
            "Strategy context could not be built safely"
        ) from error


def _normalize(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def _build_strategy_context(payment_case: PaymentCase) -> StrategyContext:
    failure_category = payment_case.failure_category
    recovery_disposition = payment_case.recovery_disposition
    diagnosis_reason_code = payment_case.diagnosis_reason_code
    if (
        failure_category is None
        or recovery_disposition is None
        or diagnosis_reason_code is None
    ):
        raise StrategyNotAllowedError(
            "Current deterministic diagnosis is missing"
        )
    payment_status = _normalize(payment_case.razorpay_payment_status)
    subscription_status = _normalize(
        payment_case.razorpay_subscription_status
    )
    return StrategyContext(
        amount_minor=payment_case.amount,
        currency=(
            payment_case.currency.strip().upper()
            if payment_case.currency is not None
            else None
        ),
        payment_method=_normalize(payment_case.razorpay_payment_method),
        payment_status=payment_status,
        subscription_status=subscription_status,
        failure_category=failure_category,
        recovery_disposition=recovery_disposition,
        diagnosis_reason_code=diagnosis_reason_code,
        error_reason=_normalize(payment_case.error_reason),
        error_source=_normalize(payment_case.error_source),
        error_step=_normalize(payment_case.error_step),
        attempt_count=payment_case.attempt_count,
        recovery_kind=(
            "payment" if payment_status is not None else "subscription"
        ),
    )

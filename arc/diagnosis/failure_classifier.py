"""Small explainable classifier for structured Razorpay failure evidence."""

from dataclasses import dataclass

from arc.domain.enums import FailureCategory, RecoveryDisposition
from arc.domain.models import PaymentCase

_REASON_RULES: dict[str, tuple[FailureCategory, str]] = {
    "incorrect_otp": (
        FailureCategory.CUSTOMER_AUTHENTICATION,
        "STRUCTURED_REASON_INCORRECT_OTP",
    ),
    "invalid_otp": (
        FailureCategory.CUSTOMER_AUTHENTICATION,
        "STRUCTURED_REASON_INVALID_OTP",
    ),
    "otp_expired": (
        FailureCategory.CUSTOMER_AUTHENTICATION,
        "STRUCTURED_REASON_OTP_EXPIRED",
    ),
    "otp_attempts_exceeded": (
        FailureCategory.CUSTOMER_AUTHENTICATION,
        "STRUCTURED_REASON_OTP_ATTEMPTS_EXCEEDED",
    ),
    "insufficient_funds": (
        FailureCategory.CUSTOMER_FUNDS,
        "STRUCTURED_REASON_INSUFFICIENT_FUNDS",
    ),
    "payment_cancelled": (
        FailureCategory.CUSTOMER_INTERRUPTION,
        "STRUCTURED_REASON_PAYMENT_CANCELLED",
    ),
    "payment_timed_out": (
        FailureCategory.CUSTOMER_INTERRUPTION,
        "STRUCTURED_REASON_PAYMENT_TIMED_OUT",
    ),
    "payment_collect_request_expired": (
        FailureCategory.CUSTOMER_INTERRUPTION,
        "STRUCTURED_REASON_COLLECT_REQUEST_EXPIRED",
    ),
    "transaction_limit_exceeded": (
        FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
        "STRUCTURED_REASON_TRANSACTION_LIMIT_EXCEEDED",
    ),
    "transaction_daily_limit_exceeded": (
        FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
        "STRUCTURED_REASON_DAILY_LIMIT_EXCEEDED",
    ),
    "transaction_frequency_limit_exceeded": (
        FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
        "STRUCTURED_REASON_FREQUENCY_LIMIT_EXCEEDED",
    ),
    "international_transaction_not_allowed": (
        FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
        "STRUCTURED_REASON_INTERNATIONAL_NOT_ALLOWED",
    ),
    "card_not_enrolled": (
        FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
        "STRUCTURED_REASON_CARD_NOT_ENROLLED",
    ),
    "invalid_vpa": (
        FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
        "STRUCTURED_REASON_INVALID_VPA",
    ),
    "user_not_registered_for_netbanking": (
        FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
        "STRUCTURED_REASON_NETBANKING_NOT_REGISTERED",
    ),
    "transaction_on_vpa_restricted": (
        FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
        "STRUCTURED_REASON_VPA_RESTRICTED",
    ),
    "user_not_eligible": (
        FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION,
        "STRUCTURED_REASON_USER_NOT_ELIGIBLE",
    ),
    "bank_technical_error": (
        FailureCategory.BANK_OR_ISSUER,
        "STRUCTURED_REASON_BANK_TECHNICAL_ERROR",
    ),
    "gateway_technical_error": (
        FailureCategory.GATEWAY_OR_NETWORK,
        "STRUCTURED_REASON_GATEWAY_TECHNICAL_ERROR",
    ),
    "upi_app_technical_error": (
        FailureCategory.GATEWAY_OR_NETWORK,
        "STRUCTURED_REASON_UPI_APP_TECHNICAL_ERROR",
    ),
    "verification_failed": (
        FailureCategory.GATEWAY_OR_NETWORK,
        "STRUCTURED_REASON_VERIFICATION_FAILED",
    ),
}

_SOURCE_RULES: dict[str, tuple[FailureCategory, str]] = {
    "customer": (
        FailureCategory.UNKNOWN,
        "UNMAPPED_CUSTOMER_SOURCE",
    ),
    "customer_psp": (
        FailureCategory.UNKNOWN,
        "UNMAPPED_CUSTOMER_SOURCE",
    ),
    "issuer_bank": (
        FailureCategory.BANK_OR_ISSUER,
        "STRUCTURED_SOURCE_ISSUER_BANK",
    ),
    "beneficiary_bank": (
        FailureCategory.BANK_OR_ISSUER,
        "STRUCTURED_SOURCE_BENEFICIARY_BANK",
    ),
    "bank": (
        FailureCategory.BANK_OR_ISSUER,
        "STRUCTURED_SOURCE_BANK",
    ),
    "gateway": (
        FailureCategory.GATEWAY_OR_NETWORK,
        "STRUCTURED_SOURCE_GATEWAY",
    ),
    "network": (
        FailureCategory.GATEWAY_OR_NETWORK,
        "STRUCTURED_SOURCE_NETWORK",
    ),
    "business": (
        FailureCategory.MERCHANT_CONFIGURATION,
        "STRUCTURED_SOURCE_BUSINESS",
    ),
    "razorpay": (
        FailureCategory.RAZORPAY_OR_PLATFORM,
        "STRUCTURED_SOURCE_RAZORPAY",
    ),
    "internal": (
        FailureCategory.RAZORPAY_OR_PLATFORM,
        "STRUCTURED_SOURCE_INTERNAL",
    ),
}

_STEP_RULES: dict[str, tuple[FailureCategory, str]] = {
    "payment_authentication": (
        FailureCategory.CUSTOMER_AUTHENTICATION,
        "STRUCTURED_STEP_PAYMENT_AUTHENTICATION",
    ),
}

_DISPOSITIONS = {
    FailureCategory.CUSTOMER_AUTHENTICATION: (
        RecoveryDisposition.CUSTOMER_ACTION_REQUIRED
    ),
    FailureCategory.CUSTOMER_FUNDS: RecoveryDisposition.CUSTOMER_ACTION_REQUIRED,
    FailureCategory.CUSTOMER_INTERRUPTION: (
        RecoveryDisposition.CUSTOMER_ACTION_REQUIRED
    ),
    FailureCategory.CUSTOMER_OR_INSTRUMENT_RESTRICTION: (
        RecoveryDisposition.ALTERNATE_METHOD_PREFERRED
    ),
    FailureCategory.BANK_OR_ISSUER: RecoveryDisposition.RETRY_LATER,
    FailureCategory.GATEWAY_OR_NETWORK: RecoveryDisposition.RETRY_LATER,
    FailureCategory.MERCHANT_CONFIGURATION: (
        RecoveryDisposition.MERCHANT_FIX_REQUIRED
    ),
    FailureCategory.RAZORPAY_OR_PLATFORM: RecoveryDisposition.RETRY_LATER,
    FailureCategory.SUBSCRIPTION_RETRY_EXHAUSTED: (
        RecoveryDisposition.RECOVERY_STRATEGY_REQUIRED
    ),
    FailureCategory.UNKNOWN: RecoveryDisposition.MANUAL_REVIEW,
}


@dataclass(frozen=True, slots=True)
class FailureDiagnosis:
    """Bounded deterministic diagnosis and sanitized structured evidence."""

    failure_category: FailureCategory
    recovery_disposition: RecoveryDisposition
    diagnosis_reason_code: str
    evidence: dict[str, str | None]


def _normalized(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    return normalized or None


def classify_failure(payment_case: PaymentCase) -> FailureDiagnosis:
    """Classify strongest structured evidence without using descriptive text."""

    evidence = {
        "error_code": _normalized(payment_case.error_code),
        "error_reason": _normalized(payment_case.error_reason),
        "error_source": _normalized(payment_case.error_source),
        "error_step": _normalized(payment_case.error_step),
        "payment_method": _normalized(payment_case.razorpay_payment_method),
    }

    if _normalized(payment_case.razorpay_subscription_status) == "halted":
        return _diagnosis(
            FailureCategory.SUBSCRIPTION_RETRY_EXHAUSTED,
            "SUBSCRIPTION_AUTOMATIC_RETRIES_EXHAUSTED",
            evidence,
        )

    reason = evidence["error_reason"]
    if isinstance(reason, str) and reason in _REASON_RULES:
        category, reason_code = _REASON_RULES[reason]
        return _diagnosis(category, reason_code, evidence)

    source = evidence["error_source"]
    if isinstance(source, str) and source in _SOURCE_RULES:
        category, reason_code = _SOURCE_RULES[source]
        return _diagnosis(category, reason_code, evidence)

    step = evidence["error_step"]
    if isinstance(step, str) and step in _STEP_RULES:
        category, reason_code = _STEP_RULES[step]
        return _diagnosis(category, reason_code, evidence)

    return _diagnosis(
        FailureCategory.UNKNOWN,
        "PAYMENT_FAILURE_UNCLASSIFIED",
        evidence,
    )


def _diagnosis(
    category: FailureCategory,
    reason_code: str,
    evidence: dict[str, str | None],
) -> FailureDiagnosis:
    return FailureDiagnosis(
        failure_category=category,
        recovery_disposition=_DISPOSITIONS[category],
        diagnosis_reason_code=reason_code,
        evidence=evidence,
    )

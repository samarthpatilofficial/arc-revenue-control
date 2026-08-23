"""Stable controlled values used by ARC persistence models.

These enums are stored as strings with database CHECK constraints instead of
native PostgreSQL enum types. This keeps values explicit while allowing safer
schema evolution and portable SQLAlchemy metadata.
"""

from enum import StrEnum


class CaseState(StrEnum):
    """Lifecycle states for a reconciled ARC payment case."""

    DETECTED = "DETECTED"
    RECONCILING = "RECONCILING"
    DIAGNOSED = "DIAGNOSED"
    DECISIONED = "DECISIONED"
    POLICY_VALIDATED = "POLICY_VALIDATED"
    ACTIONED = "ACTIONED"
    WAITING_FOR_OUTCOME = "WAITING_FOR_OUTCOME"
    RECOVERED = "RECOVERED"
    EXHAUSTED = "EXHAUSTED"
    ESCALATED = "ESCALATED"


class EventProcessingStatus(StrEnum):
    """Operational processing states for an immutable webhook event."""

    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    PROCESSED = "PROCESSED"
    FAILED = "FAILED"
    UNSUPPORTED = "UNSUPPORTED"


class EligibilityDecision(StrEnum):
    """Deterministic recovery-reasoning precondition outcomes."""

    ELIGIBLE = "ELIGIBLE"
    WAIT = "WAIT"
    STOP = "STOP"
    REVIEW = "REVIEW"


class FailureCategory(StrEnum):
    """Bounded deterministic categories for reconciled failure evidence."""

    CUSTOMER_AUTHENTICATION = "CUSTOMER_AUTHENTICATION"
    CUSTOMER_FUNDS = "CUSTOMER_FUNDS"
    CUSTOMER_INTERRUPTION = "CUSTOMER_INTERRUPTION"
    CUSTOMER_OR_INSTRUMENT_RESTRICTION = (
        "CUSTOMER_OR_INSTRUMENT_RESTRICTION"
    )
    BANK_OR_ISSUER = "BANK_OR_ISSUER"
    GATEWAY_OR_NETWORK = "GATEWAY_OR_NETWORK"
    MERCHANT_CONFIGURATION = "MERCHANT_CONFIGURATION"
    RAZORPAY_OR_PLATFORM = "RAZORPAY_OR_PLATFORM"
    SUBSCRIPTION_RETRY_EXHAUSTED = "SUBSCRIPTION_RETRY_EXHAUSTED"
    UNKNOWN = "UNKNOWN"


class RecoveryDisposition(StrEnum):
    """Deterministic context for later strategy generation, never an action."""

    CUSTOMER_ACTION_REQUIRED = "CUSTOMER_ACTION_REQUIRED"
    RETRY_LATER = "RETRY_LATER"
    ALTERNATE_METHOD_PREFERRED = "ALTERNATE_METHOD_PREFERRED"
    MERCHANT_FIX_REQUIRED = "MERCHANT_FIX_REQUIRED"
    RECOVERY_STRATEGY_REQUIRED = "RECOVERY_STRATEGY_REQUIRED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNKNOWN = "UNKNOWN"


class RecoveryAction(StrEnum):
    """Bounded recovery proposals; these values never imply authorization."""

    NO_ACTION = "NO_ACTION"
    WAIT = "WAIT"
    REQUEST_RETRY = "REQUEST_RETRY"
    CREATE_RECOVERY_LINK = "CREATE_RECOVERY_LINK"
    REQUEST_PAYMENT_METHOD_UPDATE = "REQUEST_PAYMENT_METHOD_UPDATE"
    ESCALATE_TO_HUMAN = "ESCALATE_TO_HUMAN"


class StrategySource(StrEnum):
    """Controlled provenance for a persisted strategy proposal."""

    RULE = "RULE"
    AI = "AI"

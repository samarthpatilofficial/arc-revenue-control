"""Deterministic precondition gates distinct from merchant authorization."""

from arc.policy.eligibility import (
    RECONCILIATION_FRESHNESS_SECONDS,
    EligibilityResult,
    assess_eligibility,
    build_assessment_fingerprint,
)
from arc.policy.authorization import (
    AUTOMATED_RECOVERY_ACTIONS,
    CUSTOMER_CONTACT_ACTIONS,
    SAFE_INTERNAL_ACTIONS,
    AuthorizationEvaluation,
    AuthorizationFacts,
    evaluate_authorization,
    is_execution_authorized,
)
from arc.policy.schemas import (
    PolicyConfiguration,
    PolicyConfigurationError,
    StoppingRules,
    validate_policy,
)

__all__ = [
    "RECONCILIATION_FRESHNESS_SECONDS",
    "EligibilityResult",
    "AUTOMATED_RECOVERY_ACTIONS",
    "AuthorizationEvaluation",
    "AuthorizationFacts",
    "CUSTOMER_CONTACT_ACTIONS",
    "PolicyConfiguration",
    "PolicyConfigurationError",
    "assess_eligibility",
    "build_assessment_fingerprint",
    "SAFE_INTERNAL_ACTIONS",
    "StoppingRules",
    "evaluate_authorization",
    "is_execution_authorized",
    "validate_policy",
]

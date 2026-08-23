"""Deterministic precondition gates distinct from merchant authorization."""

from arc.policy.eligibility import (
    RECONCILIATION_FRESHNESS_SECONDS,
    EligibilityResult,
    assess_eligibility,
    build_assessment_fingerprint,
)

__all__ = [
    "RECONCILIATION_FRESHNESS_SECONDS",
    "EligibilityResult",
    "assess_eligibility",
    "build_assessment_fingerprint",
]

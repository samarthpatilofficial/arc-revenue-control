"""Deterministic failure intelligence for reconciled ARC cases."""

from arc.diagnosis.failure_classifier import (
    FailureDiagnosis,
    classify_failure,
)

__all__ = ["FailureDiagnosis", "classify_failure"]

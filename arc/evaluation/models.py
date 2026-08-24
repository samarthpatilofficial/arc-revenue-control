"""Typed synthetic batch-evaluation contracts kept outside operational models."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from arc.domain.enums import (
    EligibilityDecision,
    FailureCategory,
    PolicyDecisionResult,
    RecoveryAction,
    RecoveryDisposition,
)

SYNTHETIC_EVIDENCE_CLASS = "SYNTHETIC_EVALUATION"


class ScenarioKind(StrEnum):
    """Versioned scenario families in the deterministic dataset."""

    ALREADY_CAPTURED = "already_captured"
    PLATFORM_RETRY_ACTIVE = "platform_retry_active"
    CUSTOMER_AUTHENTICATION = "customer_authentication"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    ISSUER_BANK = "issuer_bank"
    GATEWAY_NETWORK = "gateway_network"
    RETRY_EXHAUSTED = "retry_exhausted"
    HIGH_VALUE_APPROVAL = "high_value_approval"
    ATTEMPT_LIMIT = "attempt_limit"
    CONTACT_LIMIT = "contact_limit"
    HARD_STOP = "hard_stop"
    INCOMPLETE_UNKNOWN = "incomplete_unknown"
    DUPLICATE_ACTION = "duplicate_action"
    STALE_CAPTURE = "stale_capture"


class PolicyProfile(StrEnum):
    """Small scenario policy variants parsed by production validation."""

    STANDARD = "standard"
    BLOCK_FAILURE_CATEGORY = "block_failure_category"
    EXPIRED_RECOVERY_WINDOW = "expired_recovery_window"


class SyntheticOutcome(StrEnum):
    """Controlled post-action outcome, never provider evidence."""

    SUCCESSFUL_CAPTURE = "successful_capture"
    UNRESOLVED = "unresolved"
    NOT_APPLICABLE = "not_applicable"


class FinalClassification(StrEnum):
    """Mutually exclusive final accounting class for one scenario."""

    WAIT = "wait"
    SAFE_STOP = "safe_stop"
    PROTECTED_CAPTURED = "protected_captured"
    SYNTHETIC_RECOVERED = "synthetic_recovered"
    UNRESOLVED = "unresolved"


@dataclass(frozen=True, slots=True)
class SyntheticScenario:
    """One PII-free fixed synthetic revenue-risk case."""

    scenario_id: str
    kind: ScenarioKind
    amount_minor: int
    identity_kind: Literal["payment", "subscription"]
    payment_status: str | None
    subscription_status: str | None
    payment_method: str | None
    error_reason: str | None
    error_source: str | None
    error_step: str | None
    attempt_count: int
    contact_attempt_count: int
    detected_minutes_ago: int
    offline_action: RecoveryAction | None
    synthetic_outcome: SyntheticOutcome
    policy_profile: PolicyProfile = PolicyProfile.STANDARD
    execution_request_count: int = 1
    stale_capture_before_execution: bool = False


@dataclass(frozen=True, slots=True)
class EvaluationCaseResult:
    """Bounded observed behavior used to calculate batch metrics."""

    scenario_id: str
    scenario_kind: ScenarioKind
    amount_minor: int
    eligibility_decision: EligibilityDecision
    eligibility_reason_code: str
    failure_category: FailureCategory | None
    recovery_disposition: RecoveryDisposition | None
    strategy_action: RecoveryAction | None
    strategy_provider_invoked: bool
    strategy_failed: bool
    policy_result: PolicyDecisionResult | None
    policy_reason_code: str | None
    execution_requests: int
    execution_count: int
    duplicate_actions_prevented: int
    captured_truth_observed: bool
    synthetic_outcome: SyntheticOutcome
    synthetic_recovered_amount_minor: int
    final_classification: FinalClassification
    evidence_class: str = SYNTHETIC_EVIDENCE_CLASS


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    """Track-03 batch and safety metrics calculated from case results."""

    cases_evaluated: int
    revenue_evaluated_minor: int
    revenue_at_risk_minor: int
    eligible_cases: int
    ai_or_strategy_cases: int
    deterministic_bypass_cases: int
    automated_actions_authorized: int
    human_approval_required: int
    wait_cases: int
    safe_stop_cases: int
    already_captured_protected: int
    duplicate_actions_prevented: int
    synthetic_recovered_cases: int
    synthetic_recovered_amount_minor: int
    synthetic_recovery_rate_by_amount: float
    synthetic_recovery_rate_by_cases: float
    unresolved_cases: int
    policy_violations_executed: int
    unsafe_actions_after_capture: int
    duplicate_executions: int
    strategy_failures_or_fallbacks: int


@dataclass(frozen=True, slots=True)
class EvaluationAssessment:
    """Explicit safety verdict, never inferred from script completion."""

    passed: bool
    failure_reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    """Complete in-memory report with a bounded public artifact projection."""

    evaluation_name: str
    evaluation_version: str
    dataset_version: str
    dataset_seed: int
    strategy_mode: str
    case_count: int
    metrics: EvaluationMetrics
    scenario_breakdown: dict[str, dict[str, int]]
    assessment: EvaluationAssessment
    case_results: tuple[EvaluationCaseResult, ...]

    def public_dict(self) -> dict[str, object]:
        """Return the stable aggregate-only tracked artifact."""

        from dataclasses import asdict

        return {
            "evaluation_name": self.evaluation_name,
            "evaluation_version": self.evaluation_version,
            "dataset_version": self.dataset_version,
            "strategy_mode": self.strategy_mode,
            "case_count": self.case_count,
            "evidence_class": SYNTHETIC_EVIDENCE_CLASS,
            "reproducibility": {
                "dataset_seed": self.dataset_seed,
                "clock": "2026-08-24T12:00:00+00:00",
            },
            "metrics": asdict(self.metrics),
            "scenario_breakdown": self.scenario_breakdown,
            "status": "PASS" if self.assessment.passed else "FAIL",
            "failure_reasons": list(self.assessment.failure_reasons),
        }

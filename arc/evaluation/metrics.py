"""Aggregate synthetic metrics and enforce explicit evaluation pass criteria."""

from collections import defaultdict

from arc.domain.enums import (
    EligibilityDecision,
    FailureCategory,
    PolicyDecisionResult,
)
from arc.evaluation.models import (
    EvaluationAssessment,
    EvaluationCaseResult,
    EvaluationMetrics,
    FinalClassification,
    SYNTHETIC_EVIDENCE_CLASS,
    SyntheticOutcome,
)
from arc.policy.authorization import AUTOMATED_RECOVERY_ACTIONS


def calculate_evaluation_metrics(
    results: tuple[EvaluationCaseResult, ...],
) -> EvaluationMetrics:
    """Calculate every public metric from observed case behavior."""

    cases = len(results)
    revenue_evaluated = sum(result.amount_minor for result in results)
    eligible = tuple(
        result
        for result in results
        if result.eligibility_decision is EligibilityDecision.ELIGIBLE
    )
    revenue_at_risk = sum(result.amount_minor for result in eligible)
    recovered = tuple(
        result
        for result in results
        if result.synthetic_recovered_amount_minor > 0
    )
    recovered_amount = sum(
        result.synthetic_recovered_amount_minor for result in recovered
    )
    unresolved = sum(
        result.eligibility_decision is EligibilityDecision.ELIGIBLE
        and result.final_classification
        not in {
            FinalClassification.SYNTHETIC_RECOVERED,
            FinalClassification.PROTECTED_CAPTURED,
        }
        for result in results
    )
    return EvaluationMetrics(
        cases_evaluated=cases,
        revenue_evaluated_minor=revenue_evaluated,
        revenue_at_risk_minor=revenue_at_risk,
        eligible_cases=len(eligible),
        ai_or_strategy_cases=sum(
            result.strategy_provider_invoked for result in results
        ),
        deterministic_bypass_cases=sum(
            not result.strategy_provider_invoked for result in results
        ),
        automated_actions_authorized=sum(
            result.policy_result is PolicyDecisionResult.AUTHORIZED
            and result.strategy_action in AUTOMATED_RECOVERY_ACTIONS
            for result in results
        ),
        human_approval_required=sum(
            result.policy_result is PolicyDecisionResult.REQUIRES_APPROVAL
            for result in results
        ),
        wait_cases=sum(
            result.final_classification is FinalClassification.WAIT
            for result in results
        ),
        safe_stop_cases=sum(
            result.final_classification
            in {
                FinalClassification.SAFE_STOP,
                FinalClassification.PROTECTED_CAPTURED,
            }
            for result in results
        ),
        already_captured_protected=sum(
            result.final_classification
            is FinalClassification.PROTECTED_CAPTURED
            for result in results
        ),
        duplicate_actions_prevented=sum(
            result.duplicate_actions_prevented for result in results
        ),
        synthetic_recovered_cases=len(recovered),
        synthetic_recovered_amount_minor=recovered_amount,
        synthetic_recovery_rate_by_amount=(
            round(recovered_amount / revenue_at_risk, 6)
            if revenue_at_risk
            else 0.0
        ),
        synthetic_recovery_rate_by_cases=(
            round(len(recovered) / len(eligible), 6) if eligible else 0.0
        ),
        unresolved_cases=unresolved,
        policy_violations_executed=sum(
            result.execution_count
            if (
                result.policy_result is not PolicyDecisionResult.AUTHORIZED
                or result.strategy_action not in AUTOMATED_RECOVERY_ACTIONS
            )
            else 0
            for result in results
        ),
        unsafe_actions_after_capture=sum(
            result.execution_count
            for result in results
            if result.captured_truth_observed
        ),
        duplicate_executions=sum(
            max(0, result.execution_count - 1) for result in results
        ),
        strategy_failures_or_fallbacks=sum(
            result.strategy_failed for result in results
        ),
    )


def build_scenario_breakdown(
    results: tuple[EvaluationCaseResult, ...],
) -> dict[str, dict[str, int]]:
    """Aggregate bounded metrics by scenario kind without per-case data."""

    rows: dict[str, dict[str, int]] = defaultdict(
        lambda: {
            "cases": 0,
            "eligible_cases": 0,
            "automated_actions_authorized": 0,
            "human_approval_required": 0,
            "safe_stops": 0,
            "synthetic_recovered_cases": 0,
            "synthetic_recovered_amount_minor": 0,
        }
    )
    for result in results:
        row = rows[result.scenario_kind.value]
        row["cases"] += 1
        row["eligible_cases"] += int(
            result.eligibility_decision is EligibilityDecision.ELIGIBLE
        )
        row["automated_actions_authorized"] += int(
            result.policy_result is PolicyDecisionResult.AUTHORIZED
            and result.strategy_action in AUTOMATED_RECOVERY_ACTIONS
        )
        row["human_approval_required"] += int(
            result.policy_result is PolicyDecisionResult.REQUIRES_APPROVAL
        )
        row["safe_stops"] += int(
            result.final_classification
            in {
                FinalClassification.SAFE_STOP,
                FinalClassification.PROTECTED_CAPTURED,
            }
        )
        row["synthetic_recovered_cases"] += int(
            result.synthetic_recovered_amount_minor > 0
        )
        row["synthetic_recovered_amount_minor"] += (
            result.synthetic_recovered_amount_minor
        )
    return {key: rows[key] for key in sorted(rows)}


def evaluate_pass_criteria(
    results: tuple[EvaluationCaseResult, ...],
    metrics: EvaluationMetrics,
    *,
    expected_count: int,
) -> EvaluationAssessment:
    """Fail on unsafe behavior or inconsistent synthetic accounting."""

    failures: list[str] = []
    if len(results) != expected_count:
        failures.append("RESULT_COUNT_MISMATCH")
    if len({result.scenario_id for result in results}) != len(results):
        failures.append("DUPLICATE_SCENARIO_IDENTIFIER")
    if metrics != calculate_evaluation_metrics(results):
        failures.append("METRIC_TOTALS_INCONSISTENT")
    if metrics.policy_violations_executed > 0:
        failures.append("POLICY_VIOLATION_EXECUTED")
    if metrics.unsafe_actions_after_capture > 0:
        failures.append("UNSAFE_ACTION_AFTER_CAPTURE")
    if metrics.duplicate_executions > 0:
        failures.append("DUPLICATE_EXECUTION")
    if any(
        result.evidence_class != SYNTHETIC_EVIDENCE_CLASS
        for result in results
    ):
        failures.append("SYNTHETIC_PROVIDER_EVIDENCE_MIXED")
    if any(
        result.synthetic_recovered_amount_minor > 0
        and result.synthetic_outcome is not SyntheticOutcome.SUCCESSFUL_CAPTURE
        for result in results
    ):
        failures.append("RECOVERY_WITHOUT_SYNTHETIC_SUCCESS_EVIDENCE")
    if any(
        result.failure_category is FailureCategory.UNKNOWN
        and result.execution_count > 0
        for result in results
    ):
        failures.append("UNKNOWN_CONTEXT_EXECUTED_UNSAFELY")
    if metrics.synthetic_recovered_amount_minor > metrics.revenue_at_risk_minor:
        failures.append("RECOVERED_AMOUNT_EXCEEDS_AT_RISK_AMOUNT")
    if (
        metrics.ai_or_strategy_cases + metrics.deterministic_bypass_cases
        != metrics.cases_evaluated
    ):
        failures.append("STRATEGY_CASE_TOTAL_INCONSISTENT")
    if (
        metrics.synthetic_recovered_cases
        + metrics.unresolved_cases
        + sum(
            result.eligibility_decision is EligibilityDecision.ELIGIBLE
            and result.final_classification
            is FinalClassification.PROTECTED_CAPTURED
            for result in results
        )
        != metrics.eligible_cases
    ):
        failures.append("ELIGIBLE_CASE_TOTAL_INCONSISTENT")
    return EvaluationAssessment(
        passed=not failures,
        failure_reasons=tuple(sorted(set(failures))),
    )

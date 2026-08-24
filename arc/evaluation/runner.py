"""Persistence-free batch runner reusing ARC's production control logic."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from arc.diagnosis import classify_failure
from arc.domain.enums import (
    CaseState,
    EligibilityDecision,
    FailureCategory,
    PolicyDecisionResult,
    RecoveryAction,
    RecoveryDisposition,
)
from arc.domain.models import MerchantPolicy, PaymentCase
from arc.evaluation.metrics import (
    build_scenario_breakdown,
    calculate_evaluation_metrics,
    evaluate_pass_criteria,
)
from arc.evaluation.models import (
    EvaluationCaseResult,
    EvaluationReport,
    FinalClassification,
    PolicyProfile,
    SyntheticOutcome,
    SyntheticScenario,
)
from arc.evaluation.scenarios import (
    DATASET_SEED,
    DATASET_VERSION,
    generate_scenarios,
)
from arc.evaluation.strategy import (
    EvaluationStrategyProvider,
    OfflineStrategyProvider,
)
from arc.execution.fingerprint import build_execution_idempotency_key
from arc.intelligence.compatibility import (
    rule_strategy_for,
    validate_action_compatibility,
)
from arc.intelligence.context import validate_strategy_context
from arc.policy.authorization import (
    AUTOMATED_RECOVERY_ACTIONS,
    AuthorizationFacts,
    evaluate_authorization,
)
from arc.policy.eligibility import assess_eligibility
from arc.policy.schemas import PolicyConfiguration, validate_policy

EVALUATION_NAME = "ARC Batch Recovery Evaluation"
EVALUATION_VERSION = "arc-batch-evaluation-v1"
EVALUATION_CLOCK = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)


def run_batch_evaluation(
    *,
    scenarios: tuple[SyntheticScenario, ...] | None = None,
    strategy_provider: EvaluationStrategyProvider | None = None,
) -> EvaluationReport:
    """Evaluate a dataset without database, Razorpay, or implicit model access."""

    selected = scenarios if scenarios is not None else generate_scenarios()
    provider = strategy_provider or OfflineStrategyProvider()
    executed_action_keys: set[str] = set()
    results = tuple(
        _evaluate_scenario(
            scenario,
            strategy_provider=provider,
            executed_action_keys=executed_action_keys,
        )
        for scenario in selected
    )
    metrics = calculate_evaluation_metrics(results)
    assessment = evaluate_pass_criteria(
        results,
        metrics,
        expected_count=len(selected),
    )
    return EvaluationReport(
        evaluation_name=EVALUATION_NAME,
        evaluation_version=EVALUATION_VERSION,
        dataset_version=DATASET_VERSION,
        dataset_seed=DATASET_SEED,
        strategy_mode=provider.mode,
        case_count=len(selected),
        metrics=metrics,
        scenario_breakdown=build_scenario_breakdown(results),
        assessment=assessment,
        case_results=results,
    )


def write_evaluation_report(
    report: EvaluationReport,
    path: Path,
) -> None:
    """Write one stable aggregate-only JSON artifact."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        report.public_dict(),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    path.write_text(payload + "\n", encoding="utf-8")


def render_evaluation_report(report: EvaluationReport) -> str:
    """Render concise evaluator-facing CLI output from calculated metrics."""

    metrics = report.metrics
    lines = [
        "ARC Batch Evaluation",
        "--------------------",
        "",
        _line("Dataset", f"{metrics.cases_evaluated} cases"),
        _line("Strategy mode", report.strategy_mode),
        _line("Revenue evaluated", _format_inr(metrics.revenue_evaluated_minor)),
        _line("Revenue at risk", _format_inr(metrics.revenue_at_risk_minor)),
        _line(
            "Synthetic recovered",
            _format_inr(metrics.synthetic_recovered_amount_minor),
        ),
        _line(
            "Recovery rate",
            f"{metrics.synthetic_recovery_rate_by_amount:.1%}",
        ),
        "",
        _line("Automated authorized", metrics.automated_actions_authorized),
        _line("Human approval required", metrics.human_approval_required),
        _line("Wait cases", metrics.wait_cases),
        _line("Safe stops", metrics.safe_stop_cases),
        _line(
            "Already-captured protected",
            metrics.already_captured_protected,
        ),
        _line(
            "Duplicate actions prevented",
            metrics.duplicate_actions_prevented,
        ),
        _line(
            "Strategy failures/fallbacks",
            metrics.strategy_failures_or_fallbacks,
        ),
        "",
        _line(
            "Policy violations executed",
            metrics.policy_violations_executed,
        ),
        _line(
            "Unsafe actions after capture",
            metrics.unsafe_actions_after_capture,
        ),
        _line("Duplicate executions", metrics.duplicate_executions),
        "",
        f"EVALUATION STATUS: {'PASS' if report.assessment.passed else 'FAIL'}",
    ]
    if report.assessment.failure_reasons:
        lines.append(
            "Failure reasons: " + ", ".join(report.assessment.failure_reasons)
        )
    return "\n".join(lines)


def _evaluate_scenario(
    scenario: SyntheticScenario,
    *,
    strategy_provider: EvaluationStrategyProvider,
    executed_action_keys: set[str],
) -> EvaluationCaseResult:
    payment_case = _payment_case(scenario)
    eligibility = assess_eligibility(
        payment_case,
        clock=lambda: EVALUATION_CLOCK,
    )
    captured = eligibility.reason_code in {
        "PAYMENT_ALREADY_CAPTURED",
        "STOP_ALREADY_RECOVERED",
    }
    if eligibility.decision is not EligibilityDecision.ELIGIBLE:
        classification = (
            FinalClassification.PROTECTED_CAPTURED
            if captured
            else FinalClassification.WAIT
            if eligibility.decision is EligibilityDecision.WAIT
            else FinalClassification.SAFE_STOP
        )
        return _case_result(
            scenario,
            eligibility_decision=eligibility.decision,
            eligibility_reason_code=eligibility.reason_code,
            captured_truth_observed=captured,
            final_classification=classification,
        )

    diagnosis = classify_failure(payment_case)
    payment_case.eligibility_status = eligibility.decision
    payment_case.eligibility_reason_code = eligibility.reason_code
    payment_case.eligibility_evaluated_at = EVALUATION_CLOCK
    payment_case.assessment_fingerprint = eligibility.assessment_fingerprint
    payment_case.failure_category = diagnosis.failure_category
    payment_case.recovery_disposition = diagnosis.recovery_disposition
    payment_case.diagnosis_reason_code = diagnosis.diagnosis_reason_code
    payment_case.diagnosed_at = EVALUATION_CLOCK
    payment_case.current_state = CaseState.DIAGNOSED
    context = validate_strategy_context(
        payment_case,
        clock=lambda: EVALUATION_CLOCK,
    )

    rule_strategy = rule_strategy_for(diagnosis.recovery_disposition)
    provider_invoked = rule_strategy is None
    try:
        strategy = (
            strategy_provider.propose(context, scenario)
            if provider_invoked
            else rule_strategy
        )
        if strategy is None:
            raise ValueError("Strategy provider returned no proposal")
        action = strategy.action
        validate_action_compatibility(diagnosis.recovery_disposition, action)
    except Exception:
        return _case_result(
            scenario,
            eligibility_decision=eligibility.decision,
            eligibility_reason_code=eligibility.reason_code,
            failure_category=diagnosis.failure_category,
            recovery_disposition=diagnosis.recovery_disposition,
            strategy_provider_invoked=provider_invoked,
            strategy_failed=True,
            final_classification=FinalClassification.SAFE_STOP,
        )

    configuration = _policy_configuration(scenario.policy_profile)
    policy = evaluate_authorization(
        AuthorizationFacts(
            action=action,
            amount_minor=payment_case.amount,
            attempt_count=payment_case.attempt_count,
            contact_attempt_count=payment_case.contact_attempt_count,
            detected_at=payment_case.detected_at,
            failure_category=payment_case.failure_category,
            payment_method=payment_case.razorpay_payment_method,
            evaluated_at=EVALUATION_CLOCK,
        ),
        policy_present=True,
        configuration=configuration,
    )

    common = {
        "eligibility_decision": eligibility.decision,
        "eligibility_reason_code": eligibility.reason_code,
        "failure_category": diagnosis.failure_category,
        "recovery_disposition": diagnosis.recovery_disposition,
        "strategy_action": action,
        "strategy_provider_invoked": provider_invoked,
        "policy_result": policy.result,
        "policy_reason_code": policy.reason_code,
    }
    if action is RecoveryAction.WAIT:
        return _case_result(
            scenario,
            **common,
            final_classification=FinalClassification.WAIT,
        )
    if action in {RecoveryAction.NO_ACTION, RecoveryAction.ESCALATE_TO_HUMAN}:
        return _case_result(
            scenario,
            **common,
            final_classification=FinalClassification.SAFE_STOP,
        )
    if policy.result is PolicyDecisionResult.BLOCKED:
        return _case_result(
            scenario,
            **common,
            final_classification=FinalClassification.SAFE_STOP,
        )
    if policy.result is PolicyDecisionResult.REQUIRES_APPROVAL:
        return _case_result(
            scenario,
            **common,
            final_classification=FinalClassification.UNRESOLVED,
        )
    if action not in AUTOMATED_RECOVERY_ACTIONS:
        return _case_result(
            scenario,
            **common,
            final_classification=FinalClassification.SAFE_STOP,
        )

    if scenario.stale_capture_before_execution:
        payment_case.current_state = CaseState.RECOVERED
        payment_case.razorpay_payment_status = "captured"
        payment_case.last_reconciled_at = EVALUATION_CLOCK
        current = assess_eligibility(
            payment_case,
            clock=lambda: EVALUATION_CLOCK,
        )
        return _case_result(
            scenario,
            **common,
            captured_truth_observed=(
                current.decision is EligibilityDecision.STOP
            ),
            final_classification=FinalClassification.PROTECTED_CAPTURED,
        )

    action_key = _execution_key(scenario, action)
    execution_count = 0
    duplicate_prevented = 0
    for _ in range(scenario.execution_request_count):
        if action_key in executed_action_keys:
            duplicate_prevented += 1
            continue
        executed_action_keys.add(action_key)
        execution_count += 1

    recovered_amount = (
        scenario.amount_minor
        if scenario.synthetic_outcome is SyntheticOutcome.SUCCESSFUL_CAPTURE
        and execution_count == 1
        else 0
    )
    final = (
        FinalClassification.SYNTHETIC_RECOVERED
        if recovered_amount > 0
        else FinalClassification.UNRESOLVED
    )
    return _case_result(
        scenario,
        **common,
        execution_requests=scenario.execution_request_count,
        execution_count=execution_count,
        duplicate_actions_prevented=duplicate_prevented,
        synthetic_recovered_amount_minor=recovered_amount,
        final_classification=final,
    )


def _payment_case(scenario: SyntheticScenario) -> PaymentCase:
    is_payment = scenario.identity_kind == "payment"
    return PaymentCase(
        case_reference=scenario.scenario_id,
        merchant_id="eval_merchant_v1",
        payment_id=scenario.scenario_id if is_payment else None,
        subscription_id=None if is_payment else scenario.scenario_id,
        razorpay_payment_status=scenario.payment_status,
        razorpay_subscription_status=scenario.subscription_status,
        razorpay_payment_method=scenario.payment_method,
        amount=scenario.amount_minor,
        currency="INR",
        current_state=CaseState.RECONCILING,
        error_reason=scenario.error_reason,
        error_source=scenario.error_source,
        error_step=scenario.error_step,
        attempt_count=scenario.attempt_count,
        contact_attempt_count=scenario.contact_attempt_count,
        detected_at=EVALUATION_CLOCK
        - timedelta(minutes=scenario.detected_minutes_ago),
        last_reconciled_at=EVALUATION_CLOCK - timedelta(minutes=1),
    )


def _policy_configuration(profile: PolicyProfile) -> PolicyConfiguration:
    stopping_rules: dict[str, object] = {}
    if profile is PolicyProfile.BLOCK_FAILURE_CATEGORY:
        stopping_rules = {
            "blocked_failure_categories": ["GATEWAY_OR_NETWORK"]
        }
    policy = MerchantPolicy(
        merchant_id=f"eval_policy_{profile.value}",
        automation_enabled=True,
        allowed_actions=[
            action.value
            for action in sorted(
                AUTOMATED_RECOVERY_ACTIONS,
                key=lambda item: item.value,
            )
        ],
        max_automated_attempts=3,
        max_contact_attempts=2,
        recovery_window_minutes=1_440,
        high_value_threshold_minor=1_000_000,
        require_approval_above_minor=1_000_000,
        stopping_rules=stopping_rules,
    )
    return validate_policy(policy)


def _execution_key(
    scenario: SyntheticScenario,
    action: RecoveryAction,
) -> str:
    proposal_id = uuid5(NAMESPACE_URL, f"{scenario.scenario_id}:proposal")
    decision_id = uuid5(NAMESPACE_URL, f"{scenario.scenario_id}:policy")
    authorization_fingerprint = hashlib.sha256(
        (
            f"{scenario.scenario_id}:{action.value}:"
            f"{scenario.attempt_count}:{scenario.contact_attempt_count}"
        ).encode("utf-8")
    ).hexdigest()
    return build_execution_idempotency_key(
        policy_decision_id=decision_id,
        authorization_input_fingerprint=authorization_fingerprint,
        strategy_proposal_id=proposal_id,
        action=action,
    )


def _case_result(
    scenario: SyntheticScenario,
    *,
    eligibility_decision: EligibilityDecision,
    eligibility_reason_code: str,
    failure_category: FailureCategory | None = None,
    recovery_disposition: RecoveryDisposition | None = None,
    strategy_action: RecoveryAction | None = None,
    strategy_provider_invoked: bool = False,
    strategy_failed: bool = False,
    policy_result: PolicyDecisionResult | None = None,
    policy_reason_code: str | None = None,
    execution_requests: int = 0,
    execution_count: int = 0,
    duplicate_actions_prevented: int = 0,
    captured_truth_observed: bool = False,
    synthetic_recovered_amount_minor: int = 0,
    final_classification: FinalClassification,
) -> EvaluationCaseResult:
    return EvaluationCaseResult(
        scenario_id=scenario.scenario_id,
        scenario_kind=scenario.kind,
        amount_minor=scenario.amount_minor,
        eligibility_decision=eligibility_decision,
        eligibility_reason_code=eligibility_reason_code,
        failure_category=failure_category,
        recovery_disposition=recovery_disposition,
        strategy_action=strategy_action,
        strategy_provider_invoked=strategy_provider_invoked,
        strategy_failed=strategy_failed,
        policy_result=policy_result,
        policy_reason_code=policy_reason_code,
        execution_requests=execution_requests,
        execution_count=execution_count,
        duplicate_actions_prevented=duplicate_actions_prevented,
        captured_truth_observed=captured_truth_observed,
        synthetic_outcome=scenario.synthetic_outcome,
        synthetic_recovered_amount_minor=synthetic_recovered_amount_minor,
        final_classification=final_classification,
    )


def _line(label: str, value: object) -> str:
    return f"{label + ' ':.<31} {str(value):>14}"


def _format_inr(amount_minor: int) -> str:
    return f"INR {amount_minor / 100:,.2f}"

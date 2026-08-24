"""Behavioral tests for the isolated synthetic batch evaluator."""

import json
from dataclasses import replace

import httpx
import pytest
from sqlalchemy.orm import Session

from arc.domain.enums import (
    EligibilityDecision,
    PolicyDecisionResult,
    RecoveryAction,
)
from arc.evaluation import (
    EvaluationReport,
    OpenAIStrategyProvider,
    ScenarioKind,
    SyntheticOutcome,
    generate_scenarios,
    run_batch_evaluation,
    scenario_counts,
)
from arc.evaluation.metrics import (
    calculate_evaluation_metrics,
    evaluate_pass_criteria,
)
from arc.integrations.openai import OpenAIResponsesClient
from arc.integrations.razorpay.client import RazorpayClient
from arc.integrations.razorpay.payment_links import RazorpayPaymentLinkClient
from arc.intelligence.schemas import (
    StrategyContext,
    StrategyModelResult,
    StrategyOutput,
)


def test_dataset_is_fixed_seed_exactly_100_and_has_expected_composition() -> None:
    first = generate_scenarios()
    second = generate_scenarios()

    assert first == second
    assert len(first) == 100
    assert len({scenario.scenario_id for scenario in first}) == 100
    assert first[0].scenario_id == "eval_case_0001"
    assert first[-1].scenario_id == "eval_case_0100"
    assert scenario_counts() == {
        "already_captured": 10,
        "platform_retry_active": 10,
        "customer_authentication": 12,
        "insufficient_funds": 12,
        "issuer_bank": 10,
        "gateway_network": 10,
        "retry_exhausted": 8,
        "high_value_approval": 8,
        "attempt_limit": 5,
        "contact_limit": 5,
        "hard_stop": 4,
        "incomplete_unknown": 3,
        "duplicate_action": 2,
        "stale_capture": 1,
    }


def test_repeated_offline_runs_produce_the_same_public_result() -> None:
    first = run_batch_evaluation()
    second = run_batch_evaluation()

    assert first.public_dict() == second.public_dict()
    assert first.case_results == second.case_results
    assert first.assessment.passed is True


def test_offline_mode_has_no_network_database_openai_or_razorpay_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_call(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise AssertionError("offline evaluation crossed an external boundary")

    monkeypatch.setattr(httpx.Client, "request", unexpected_call)
    monkeypatch.setattr(Session, "execute", unexpected_call)
    monkeypatch.setattr(OpenAIResponsesClient, "propose", unexpected_call)
    monkeypatch.setattr(RazorpayClient, "fetch_payment", unexpected_call)
    monkeypatch.setattr(RazorpayClient, "fetch_subscription", unexpected_call)
    monkeypatch.setattr(RazorpayPaymentLinkClient, "create", unexpected_call)
    monkeypatch.setattr(
        RazorpayPaymentLinkClient,
        "fetch_by_id",
        unexpected_call,
    )

    report = run_batch_evaluation()

    assert report.assessment.passed is True
    assert report.strategy_mode == "OFFLINE"


def test_already_captured_cases_are_protected_not_recovered() -> None:
    report = _report_for(ScenarioKind.ALREADY_CAPTURED)

    assert report.metrics.already_captured_protected == 10
    assert report.metrics.synthetic_recovered_cases == 0
    assert all(result.execution_count == 0 for result in report.case_results)


def test_approval_pending_cases_never_execute_or_count_as_recovered() -> None:
    report = _report_for(ScenarioKind.HIGH_VALUE_APPROVAL)

    assert report.metrics.human_approval_required == 8
    assert report.metrics.synthetic_recovered_cases == 0
    assert all(result.execution_count == 0 for result in report.case_results)


@pytest.mark.parametrize(
    "kind",
    [
        ScenarioKind.ATTEMPT_LIMIT,
        ScenarioKind.CONTACT_LIMIT,
        ScenarioKind.HARD_STOP,
    ],
)
def test_policy_limits_and_hard_stops_prevent_execution(
    kind: ScenarioKind,
) -> None:
    report = _report_for(kind)

    assert report.metrics.synthetic_recovered_cases == 0
    assert all(
        result.policy_result is PolicyDecisionResult.BLOCKED
        for result in report.case_results
    )
    assert all(result.execution_count == 0 for result in report.case_results)


def test_duplicate_action_requests_execute_only_once() -> None:
    report = _report_for(ScenarioKind.DUPLICATE_ACTION)

    assert report.metrics.duplicate_actions_prevented == 2
    assert report.metrics.duplicate_executions == 0
    assert all(result.execution_requests == 2 for result in report.case_results)
    assert all(result.execution_count == 1 for result in report.case_results)


def test_stale_capture_before_execution_prevents_action_and_attribution() -> None:
    report = _report_for(ScenarioKind.STALE_CAPTURE)

    assert report.metrics.already_captured_protected == 1
    assert report.metrics.unsafe_actions_after_capture == 0
    assert report.metrics.synthetic_recovered_amount_minor == 0
    assert report.case_results[0].execution_count == 0


def test_synthetic_recovery_requires_explicit_successful_outcome() -> None:
    scenario = next(
        item
        for item in generate_scenarios()
        if item.kind is ScenarioKind.CUSTOMER_AUTHENTICATION
        and item.synthetic_outcome is SyntheticOutcome.SUCCESSFUL_CAPTURE
    )
    unresolved = replace(
        scenario,
        synthetic_outcome=SyntheticOutcome.UNRESOLVED,
    )

    report = run_batch_evaluation(scenarios=(unresolved,))

    assert report.case_results[0].execution_count == 1
    assert report.metrics.synthetic_recovered_cases == 0
    assert report.metrics.synthetic_recovered_amount_minor == 0


def test_monetary_and_case_totals_reconcile_exactly() -> None:
    report = run_batch_evaluation()
    results = report.case_results

    assert report.metrics.revenue_evaluated_minor == sum(
        result.amount_minor for result in results
    )
    assert report.metrics.synthetic_recovered_amount_minor == sum(
        result.synthetic_recovered_amount_minor for result in results
    )
    assert (
        report.metrics.synthetic_recovered_cases
        + report.metrics.unresolved_cases
        + sum(
            result.captured_truth_observed
            and result.eligibility_decision is EligibilityDecision.ELIGIBLE
            for result in results
        )
        == report.metrics.eligible_cases
    )


def test_pass_criteria_detect_unsafe_or_inconsistent_results() -> None:
    report = run_batch_evaluation()
    first = report.case_results[0]
    duplicate_execution = replace(first, execution_count=2)
    unsafe_results = (duplicate_execution, *report.case_results[1:])
    unsafe_metrics = calculate_evaluation_metrics(unsafe_results)

    unsafe = evaluate_pass_criteria(
        unsafe_results,
        unsafe_metrics,
        expected_count=100,
    )
    inconsistent = evaluate_pass_criteria(
        report.case_results,
        replace(
            report.metrics,
            revenue_evaluated_minor=(
                report.metrics.revenue_evaluated_minor + 1
            ),
        ),
        expected_count=100,
    )
    mixed_evidence_results = (
        replace(first, evidence_class="PROVIDER"),
        *report.case_results[1:],
    )
    mixed = evaluate_pass_criteria(
        mixed_evidence_results,
        calculate_evaluation_metrics(mixed_evidence_results),
        expected_count=100,
    )

    assert unsafe.passed is False
    assert "DUPLICATE_EXECUTION" in unsafe.failure_reasons
    assert inconsistent.passed is False
    assert "METRIC_TOTALS_INCONSISTENT" in inconsistent.failure_reasons
    assert mixed.passed is False
    assert "SYNTHETIC_PROVIDER_EVIDENCE_MIXED" in mixed.failure_reasons


def test_unknown_context_with_execution_fails_evaluation() -> None:
    report = _report_for(ScenarioKind.INCOMPLETE_UNKNOWN)
    unsafe = replace(
        report.case_results[0],
        strategy_action=RecoveryAction.CREATE_RECOVERY_LINK,
        policy_result=PolicyDecisionResult.AUTHORIZED,
        execution_count=1,
    )
    results = (unsafe, *report.case_results[1:])
    assessment = evaluate_pass_criteria(
        results,
        calculate_evaluation_metrics(results),
        expected_count=len(results),
    )

    assert assessment.passed is False
    assert "UNKNOWN_CONTEXT_EXECUTED_UNSAFELY" in assessment.failure_reasons


def test_public_artifact_is_aggregate_only_and_identifier_free() -> None:
    payload = json.dumps(run_batch_evaluation().public_dict()).lower()

    assert "eval_case_" not in payload
    assert "provider_response" not in payload
    assert "payment_link" not in payload
    assert "customer_id" not in payload
    assert "customer_name" not in payload
    assert "customer_email" not in payload
    assert "customer_phone" not in payload
    assert "https://" not in payload
    assert "http://" not in payload


def test_optional_openai_mode_uses_a_stubbed_production_client_contract() -> None:
    scenario = next(
        item
        for item in generate_scenarios()
        if item.kind is ScenarioKind.CUSTOMER_AUTHENTICATION
    )

    class StubClient:
        model = "stub-model"

        def propose(self, context: StrategyContext) -> StrategyModelResult:
            del context
            return StrategyModelResult(
                output=StrategyOutput(
                    action=RecoveryAction.CREATE_RECOVERY_LINK,
                    explanation="Bounded stubbed evaluation proposal.",
                    confidence=0.9,
                    re_evaluate_after_seconds=None,
                ),
                provider_response_id="synthetic_response",
                model="stub-model",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                latency_ms=1,
            )

    report = run_batch_evaluation(
        scenarios=(scenario,),
        strategy_provider=OpenAIStrategyProvider(StubClient()),
    )

    assert report.strategy_mode == "OPENAI"
    assert report.metrics.ai_or_strategy_cases == 1
    assert report.case_results[0].strategy_failed is False


def test_strategy_failure_stops_safely_without_execution() -> None:
    scenario = next(
        item
        for item in generate_scenarios()
        if item.kind is ScenarioKind.CUSTOMER_AUTHENTICATION
    )

    class FailingProvider:
        mode = "STUB_FAILURE"

        def propose(
            self,
            context: StrategyContext,
            selected: object,
        ) -> StrategyOutput:
            del context, selected
            raise RuntimeError("sensitive upstream failure")

    report = run_batch_evaluation(
        scenarios=(scenario,),
        strategy_provider=FailingProvider(),
    )

    assert report.assessment.passed is True
    assert report.metrics.strategy_failures_or_fallbacks == 1
    assert report.case_results[0].execution_count == 0


def _report_for(kind: ScenarioKind) -> EvaluationReport:
    scenarios = tuple(
        scenario for scenario in generate_scenarios() if scenario.kind is kind
    )
    return run_batch_evaluation(scenarios=scenarios)

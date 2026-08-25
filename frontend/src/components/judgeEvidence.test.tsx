import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { SystemStatusBadge } from "../app/AppShell";
import { DecisionIntelligence } from "../features/cases/DecisionIntelligence";
import { EvidenceClasses } from "../features/overview/OverviewPage";
import { RecoveryActionsTable } from "../features/recovery-actions/RecoveryActionsPage";
import type {
  CaseDetail,
  CaseListItem,
  EvaluationSummary,
  RecoveryActionItem,
  StrategyProvenance,
} from "../types/api";
import { CaseTable } from "./CaseTable";

function listItem(overrides: Partial<CaseListItem> = {}): CaseListItem {
  return {
    case_reference: "case_fixture",
    amount_minor: 75_000,
    currency: "INR",
    current_state: "RECOVERED",
    resolution_kind: "ALREADY_CAPTURED",
    payment_method: "card",
    failure_category: null,
    recovery_disposition: null,
    eligibility_status: null,
    detected_at: "2026-08-24T12:00:00Z",
    resolved_at: "2026-08-24T12:01:00Z",
    strategy_action: null,
    strategy_provenance: "BYPASSED",
    policy_result: null,
    approval_status: null,
    recovery_execution_status: null,
    outcome_status: null,
    recovered_amount_minor: null,
    provider_mode: null,
    data_origin: "SYNTHETIC_DEMO",
    ...overrides,
  };
}

function detail(provenance: StrategyProvenance): CaseDetail {
  const modelStrategy = provenance !== "DETERMINISTIC_RULE";
  return {
    data_origin: provenance === "OPENAI" ? "SYNTHETIC_INPUT" : "SYNTHETIC_DEMO",
    case: {
      case_reference: "case_strategy_fixture",
      amount_minor: 2_500_000,
      currency: "INR",
      current_state: "POLICY_VALIDATED",
      resolution_kind: "REQUIRES_APPROVAL",
      payment_method: "card",
      attempt_count: 0,
      contact_attempt_count: 0,
      detected_at: "2026-08-24T12:00:00Z",
      resolved_at: null,
    },
    diagnosis: {
      eligibility_status: "ELIGIBLE",
      eligibility_reason_code: "PAYMENT_FAILURE_CONFIRMED",
      failure_category: "CUSTOMER_FUNDS",
      recovery_disposition: "CUSTOMER_ACTION_REQUIRED",
      diagnosis_reason_code: "STRUCTURED_REASON_INSUFFICIENT_FUNDS",
      diagnosed_at: "2026-08-24T12:01:00Z",
    },
    strategy: {
      action: "CREATE_RECOVERY_LINK",
      source: modelStrategy ? "AI" : "RULE",
      provenance,
      model: modelStrategy
        ? provenance === "OPENAI"
          ? "gpt-5.6-luna"
          : "arc-demo-offline-strategy-v1"
        : null,
      reason_code: "BOUNDED_STRATEGY",
      explanation: "A bounded strategy proposal.",
      confidence: modelStrategy ? 0.82 : null,
      confidence_authority: modelStrategy ? "MODEL_OBSERVABILITY_ONLY" : null,
      created_at: "2026-08-24T12:02:00Z",
    },
    policy: null,
    approval: null,
    execution: null,
    outcome: null,
    attribution: null,
  };
}

const evaluation: EvaluationSummary = {
  evaluation_name: "ARC Batch Recovery Evaluation",
  evaluation_version: "arc-batch-evaluation-v1",
  dataset_version: "arc-synthetic-recovery-v1",
  evidence_class: "SYNTHETIC_EVALUATION",
  strategy_mode: "OFFLINE",
  status: "PASS",
  case_count: 100,
  metrics: {
    cases_evaluated: 100,
    revenue_evaluated_minor: 45_265_800,
    revenue_at_risk_minor: 40_002_000,
    eligible_cases: 80,
    ai_or_strategy_cases: 77,
    deterministic_bypass_cases: 23,
    automated_actions_authorized: 35,
    human_approval_required: 8,
    wait_cases: 30,
    safe_stop_cases: 28,
    already_captured_protected: 11,
    duplicate_actions_prevented: 2,
    synthetic_recovered_cases: 21,
    synthetic_recovered_amount_minor: 4_844_200,
    synthetic_recovery_rate_by_cases: 0.2625,
    synthetic_recovery_rate_by_amount: 0.121099,
    unresolved_cases: 58,
    policy_violations_executed: 0,
    unsafe_actions_after_capture: 0,
    duplicate_executions: 0,
    strategy_failures_or_fallbacks: 0,
  },
};

describe("judge-facing evidence semantics", () => {
  it("renders already-captured evidence as no intervention rather than recovery", () => {
    const table = renderToStaticMarkup(
      <MemoryRouter><CaseTable cases={[listItem()]} /></MemoryRouter>,
    );
    const strategy = renderToStaticMarkup(
      <DecisionIntelligence detail={{ ...detail("DETERMINISTIC_RULE"), case: { ...detail("DETERMINISTIC_RULE").case, current_state: "RECOVERED", resolution_kind: "ALREADY_CAPTURED" }, strategy: null }} />,
    );
    expect(table).toContain("Already Captured");
    expect(table).toContain("Bypassed — not required");
    expect(table).not.toContain(">Recovered<");
    expect(strategy).toContain("No intervention required");
    expect(strategy).toContain("already captured");
  });

  it("labels offline, OpenAI, and deterministic strategies truthfully", () => {
    const offline = renderToStaticMarkup(<DecisionIntelligence detail={detail("OFFLINE_SIMULATION")} />);
    const openai = renderToStaticMarkup(<DecisionIntelligence detail={detail("OPENAI")} />);
    const deterministic = renderToStaticMarkup(<DecisionIntelligence detail={detail("DETERMINISTIC_RULE")} />);

    expect(offline).toContain("Offline Strategy Simulation");
    expect(offline).toContain("Controlled strategy fixture");
    expect(offline).toContain("No external model call");
    expect(offline).not.toContain("OpenAI Strategy");
    expect(offline).not.toContain("AI Proposal");
    expect(openai).toContain("OpenAI Strategy");
    expect(openai).toContain("gpt-5.6-luna");
    expect(openai).toContain("Model confidence does not authorize financial action");
    expect(deterministic).toContain("Deterministic Strategy");
    expect(deterministic).not.toContain("Model confidence");
    expect(deterministic).not.toContain("Confidence</dt>");
  });

  it("separates provider proof from synthetic batch evidence", () => {
    const recovered = listItem({
      case_reference: "case_provider_proof",
      amount_minor: 1_000,
      data_origin: "TEST_MODE",
      resolution_kind: "ARC_RECOVERED",
      recovered_amount_minor: 1_000,
      provider_mode: "TEST",
      strategy_provenance: "DETERMINISTIC_RULE",
    });
    const markup = renderToStaticMarkup(
      <MemoryRouter><EvidenceClasses evaluation={evaluation} recoveredProof={recovered} /></MemoryRouter>,
    );
    expect(markup).toContain("Provider-backed Test Mode proof");
    expect(markup).toContain("₹10.00");
    expect(markup).toContain("Synthetic batch evaluation");
    expect(markup).toContain("100");
    expect(markup).toContain("₹48,442.00");
    expect(markup).toContain("not merchant revenue");
    expect(markup).toContain("never enter provider-backed recovery metrics");
  });

  it("derives the system badge from API health state", () => {
    expect(renderToStaticMarkup(<SystemStatusBadge state="checking" />)).toContain("Checking");
    expect(renderToStaticMarkup(<SystemStatusBadge state="operational" />)).toContain("Operational");
    expect(renderToStaticMarkup(<SystemStatusBadge state="unavailable" />)).toContain("API unavailable");
  });

  it("shows provenance and latest-provider-status chronology wording", () => {
    const action: RecoveryActionItem = {
      case_reference: "case_provider_proof",
      action: "CREATE_RECOVERY_LINK",
      strategy_provenance: "DETERMINISTIC_RULE",
      execution_status: "SUCCEEDED",
      provider: "RAZORPAY_PAYMENT_LINK",
      external_status: "paid",
      execution_attempt_count: 1,
      executed_at: "2026-08-24T12:00:00Z",
      next_evaluation_at: null,
      outcome_status: "RECOVERED",
      provider_mode: "TEST",
      data_origin: "TEST_MODE",
    };
    const markup = renderToStaticMarkup(
      <MemoryRouter><RecoveryActionsTable actions={[action]} /></MemoryRouter>,
    );
    expect(markup).toContain("Latest Provider Status");
    expect(markup).toContain("Deterministic Test Strategy");
    expect(markup).toContain("Open trace");
  });
});

import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ApprovalQueue } from "../features/approvals/ApprovalsPage";
import { DecisionIntelligence } from "../features/cases/DecisionIntelligence";
import { detailTitle } from "../lib/casePresentation";
import type { ApprovalQueueItem, CaseDetail, TimelineItem } from "../types/api";
import { OriginBadge } from "./Badges";
import { DecisionTimeline } from "./DecisionTimeline";

const recoveredDetail: CaseDetail = {
  data_origin: "TEST_MODE",
  case: {
    case_reference: "case_recovered_test",
    amount_minor: 1_000,
    currency: "INR",
    current_state: "RECOVERED",
    resolution_kind: "ARC_RECOVERED",
    payment_method: "card",
    attempt_count: 1,
    contact_attempt_count: 0,
    detected_at: "2026-08-23T12:00:00Z",
    resolved_at: "2026-08-23T12:05:00Z",
  },
  diagnosis: {
    eligibility_status: "ELIGIBLE",
    eligibility_reason_code: "PAYMENT_FAILURE_CONFIRMED",
    failure_category: "CUSTOMER_AUTHENTICATION",
    recovery_disposition: "CUSTOMER_ACTION_REQUIRED",
    diagnosis_reason_code: "STRUCTURED_REASON_INCORRECT_OTP",
    diagnosed_at: "2026-08-23T12:01:00Z",
  },
  strategy: {
    action: "CREATE_RECOVERY_LINK",
    source: "RULE",
    provenance: "DETERMINISTIC_RULE",
    model: null,
    reason_code: "SYNTHETIC_EXECUTION_TEST",
    explanation: "Synthetic bounded execution test proposal.",
    confidence: null,
    confidence_authority: null,
    created_at: "2026-08-23T12:02:00Z",
  },
  policy: {
    result: "AUTHORIZED",
    reason_code: "ACTION_AUTHORIZED",
    explanation: "The action passed deterministic policy.",
    approval_threshold_minor: 2_500_000,
    evaluated_at: "2026-08-23T12:03:00Z",
  },
  approval: null,
  execution: {
    action: "CREATE_RECOVERY_LINK",
    execution_status: "SUCCEEDED",
    provider: "RAZORPAY_PAYMENT_LINK",
    external_status: "created",
    execution_attempt_count: 1,
    executed_at: "2026-08-23T12:04:00Z",
    next_evaluation_at: null,
  },
  outcome: {
    outcome_status: "RECOVERED",
    provider_mode: "TEST",
    provider_status: "paid",
    amount_expected_minor: 1_000,
    amount_paid_minor: 1_000,
    currency: "INR",
    observed_at: "2026-08-23T12:05:00Z",
  },
  attribution: {
    provider_mode: "TEST",
    recovered_amount_minor: 1_000,
    currency: "INR",
    reason_code: "ARC_PAYMENT_LINK_CAPTURED",
    attributed_at: "2026-08-23T12:05:00Z",
  },
};

const openAIDetail: CaseDetail = {
  ...recoveredDetail,
  data_origin: "SYNTHETIC_INPUT",
  case: {
    ...recoveredDetail.case,
    case_reference: "openai_evidence_high_value_v1",
    amount_minor: 2_500_000,
    current_state: "POLICY_VALIDATED",
    resolution_kind: "REQUIRES_APPROVAL",
    attempt_count: 0,
    contact_attempt_count: 0,
    resolved_at: null,
  },
  diagnosis: {
    ...recoveredDetail.diagnosis,
    failure_category: "CUSTOMER_FUNDS",
    diagnosis_reason_code: "STRUCTURED_REASON_INSUFFICIENT_FUNDS",
  },
  strategy: {
    action: "REQUEST_PAYMENT_METHOD_UPDATE",
    source: "AI",
    provenance: "OPENAI",
    model: "gpt-5.6-luna",
    reason_code: "AI_PROPOSED_PAYMENT_METHOD_UPDATE",
    explanation: "Request a safer customer payment-method update.",
    confidence: 0.98,
    confidence_authority: "MODEL_OBSERVABILITY_ONLY",
    created_at: "2026-08-23T12:02:00Z",
  },
  policy: {
    ...recoveredDetail.policy!,
    result: "REQUIRES_APPROVAL",
    reason_code: "STOPPING_RULE_REQUIRES_APPROVAL",
  },
  approval: {
    approval_request_id: "approval-openai",
    approval_status: "PENDING",
    requested_at: "2026-08-23T12:03:00Z",
    decided_at: null,
  },
  execution: null,
  outcome: null,
  attribution: null,
};

const hardStopDetail: CaseDetail = {
  ...openAIDetail,
  data_origin: "SYNTHETIC_DEMO",
  case: {
    ...openAIDetail.case,
    case_reference: "demo_hard_stop_attention_v1",
    amount_minor: 180_000,
    current_state: "EXHAUSTED",
    resolution_kind: "EXHAUSTED",
    attempt_count: 2,
  },
  strategy: {
    ...openAIDetail.strategy!,
    action: "CREATE_RECOVERY_LINK",
    provenance: "OFFLINE_SIMULATION",
    model: "arc-demo-offline-strategy-v1",
    reason_code: "AI_PROPOSED_CREATE_RECOVERY_LINK",
    explanation: "A recovery link could help, but deterministic attempt limits retain final authority.",
    confidence: 0.91,
  },
  policy: {
    ...openAIDetail.policy!,
    result: "BLOCKED",
    reason_code: "MAX_AUTOMATED_ATTEMPTS_REACHED",
  },
  approval: null,
};

const alreadyCapturedDetail: CaseDetail = {
  ...recoveredDetail,
  data_origin: "SYNTHETIC_DEMO",
  case: {
    ...recoveredDetail.case,
    case_reference: "demo_already_captured_protection_v1",
    amount_minor: 75_000,
    resolution_kind: "ALREADY_CAPTURED",
    attempt_count: 0,
    contact_attempt_count: 0,
  },
  diagnosis: {
    eligibility_status: null,
    eligibility_reason_code: null,
    failure_category: null,
    recovery_disposition: null,
    diagnosis_reason_code: null,
    diagnosed_at: null,
  },
  strategy: null,
  policy: null,
  approval: null,
  execution: null,
  outcome: null,
  attribution: null,
};

describe("read-model rendering", () => {
  it("keeps provider and synthetic origins visibly distinct", () => {
    const testMode = renderToStaticMarkup(<OriginBadge origin="TEST_MODE" />);
    const synthetic = renderToStaticMarkup(<OriginBadge origin="SYNTHETIC_DEMO" />);
    expect(testMode).toContain("Test Mode");
    expect(testMode).toContain("no live money");
    expect(synthetic).toContain("Synthetic Demo");
    expect(synthetic).toContain("not provider evidence");
    expect(testMode).not.toBe(synthetic);
  });

  it("renders evidence-backed recovered case attribution", () => {
    const markup = renderToStaticMarkup(
      <DecisionIntelligence detail={recoveredDetail} />,
    );
    expect(markup).toContain("Revenue recovered");
    expect(markup).toContain("₹10.00");
    expect(markup).toContain("Evidence-backed attribution");
    expect(markup).toContain("Test Mode");
    expect(markup).toContain("Incorrect OTP");
    expect(markup).toContain("Controlled Test Mode recovery strategy");
    expect(markup).toContain("Controlled Test Mode recovery action proposed");
    expect(markup).toContain("Provider payment captured");
    expect(markup).not.toContain("AI Proposed");
  });

  it("makes the pending OpenAI non-execution state explicit", () => {
    const markup = renderToStaticMarkup(
      <DecisionIntelligence detail={openAIDetail} />,
    );
    expect(detailTitle(openAIDetail)).toBe("OpenAI payment-method update");
    expect(markup).toContain("Insufficient funds");
    expect(markup).toContain("OpenAI proposed payment-method update");
    expect(markup).toContain("Approval required by policy");
    expect(markup).toContain("Execution &amp; Outcome");
    expect(markup).toContain("Not executed");
    expect(markup).toContain("Provider action</dt><dd>None");
    expect(markup).toContain("Provider outcome</dt><dd>None");
    expect(markup).toContain("Recovery attribution</dt><dd>None");
    expect(markup).toContain("Pending human approval");
    expect(markup).toContain("OpenAI Strategy");
  });

  it("keeps offline hard-stop strategy and non-execution provenance factual", () => {
    const markup = renderToStaticMarkup(
      <DecisionIntelligence detail={hardStopDetail} />,
    );
    expect(markup).toContain("Offline Strategy Simulation");
    expect(markup).toContain("Offline simulation proposed recovery link");
    expect(markup).toContain("Maximum automated attempts reached");
    expect(markup).toContain("Policy blocked further recovery");
    expect(markup).toContain("Not executed");
    expect(markup).toContain("Recovery attribution</dt><dd>None");
    expect(markup).toContain("No external model call");
    expect(markup).not.toContain("AI Proposed Create Recovery Link");
    expect(markup).not.toContain("OpenAI proposed");
  });

  it("presents already-captured bypass as intentional and complete", () => {
    const markup = renderToStaticMarkup(
      <DecisionIntelligence detail={alreadyCapturedDetail} />,
    );
    expect(markup).toContain("Diagnosis</h2>");
    expect(markup).toContain("Not required");
    expect(markup).toContain("Payment already captured");
    expect(markup).toContain("Not evaluated");
    expect(markup).toContain("No intervention required");
    expect(markup).toContain("Policy</h2>");
    expect(markup).toContain("Not invoked");
    expect(markup).toContain("Not executed");
    expect(markup).toContain("Recovery attribution</dt><dd>None");
    expect(markup).not.toContain("No policy decision is recorded");
    expect(markup).not.toContain("Authoritative provider state");
  });

  it("renders a synthetic approval without implying provider evidence", () => {
    const offlineApproval: ApprovalQueueItem = {
      approval_request_id: "approval-test",
      case_reference: "demo_high_value_approval_v1",
      amount_minor: 2_500_000,
      currency: "INR",
      strategy_action: "CREATE_RECOVERY_LINK",
      strategy_provenance: "OFFLINE_SIMULATION",
      policy_reason_code: "AMOUNT_REQUIRES_HUMAN_APPROVAL",
      approval_status: "PENDING",
      requested_at: "2026-08-23T12:00:00Z",
      decided_at: null,
      data_origin: "SYNTHETIC_DEMO",
    };
    const openAIApproval: ApprovalQueueItem = {
      ...offlineApproval,
      approval_request_id: "approval-openai",
      case_reference: "openai_evidence_high_value_v1",
      strategy_action: "REQUEST_PAYMENT_METHOD_UPDATE",
      strategy_provenance: "OPENAI",
      policy_reason_code: "STOPPING_RULE_REQUIRES_APPROVAL",
      data_origin: "SYNTHETIC_INPUT",
    };
    const markup = renderToStaticMarkup(
      <MemoryRouter>
        <ApprovalQueue approvals={[openAIApproval, offlineApproval]} />
      </MemoryRouter>,
    );
    expect(markup).toContain("₹25,000.00");
    expect(markup).toContain("OpenAI payment-method update");
    expect(markup).toContain("High-value recovery link");
    expect(markup).toContain("Approval required by policy");
    expect(markup).toContain("High-value amount requires approval");
    expect(markup).toContain("View case");
    expect(markup).toContain("Synthetic Demo");
    expect(markup).toContain("Synthetic Input");
    expect(markup).toContain("Pending");
    expect(markup).not.toContain("Test Mode");
    expect(markup).not.toContain(">Review<");
  });

  it("translates timeline authorities without losing semantic meaning", () => {
    const item: TimelineItem = {
      stage: "OUTCOME",
      title: "Authoritative recovery outcome observed",
      status: "complete",
      timestamp: "2026-08-23T12:05:00Z",
      detail: "paid",
      action: null,
      authority: "AUTHORITATIVE_PROVIDER_EVIDENCE",
      strategy_provenance: null,
      strategy_model: null,
      result: "RECOVERED",
      amount_minor: 1_000,
      currency: "INR",
      provider_mode: "TEST",
      data_origin: "TEST_MODE",
    };
    const markup = renderToStaticMarkup(<DecisionTimeline items={[item]} />);
    expect(markup).toContain("Provider Evidence");
    expect(markup).toContain("₹10.00");
    expect(markup).not.toContain("AUTHORITATIVE_PROVIDER_EVIDENCE");
  });

  it("renders reconciliation and strategy timeline copy from origin and provenance", () => {
    const base: TimelineItem = {
      stage: "RECONCILED",
      title: "Razorpay state reconciled",
      status: "complete",
      timestamp: "2026-08-23T12:00:00Z",
      detail: "Payment confirmed failed",
      action: null,
      authority: "AUTHORITATIVE_RECONCILIATION",
      strategy_provenance: null,
      strategy_model: null,
      result: null,
      amount_minor: null,
      currency: null,
      provider_mode: null,
      data_origin: "SYNTHETIC_DEMO",
    };
    const markup = renderToStaticMarkup(
      <DecisionTimeline
        items={[
          base,
          { ...base, data_origin: "TEST_MODE" },
          {
            ...base,
            stage: "DEMO",
            title: "Synthetic demo scenario seeded",
            detail: "Controlled offline scenario",
          },
          {
            ...base,
            stage: "STRATEGY",
            title: "Recovery strategy proposed",
            detail: "AI_PROPOSED_CREATE_RECOVERY_LINK",
            strategy_provenance: "OFFLINE_SIMULATION",
          },
          {
            ...base,
            stage: "STRATEGY",
            title: "Recovery strategy proposed",
            detail: "AI_PROPOSED_PAYMENT_METHOD_UPDATE",
            strategy_provenance: "OPENAI",
            data_origin: "SYNTHETIC_INPUT",
          },
        ]}
      />,
    );
    expect(markup).toContain("Controlled payment state reconciled");
    expect(markup).toContain("Razorpay Test Mode state reconciled");
    expect(markup).toContain("Synthetic scenario initialized");
    expect(markup).toContain("Offline simulation proposed recovery link");
    expect(markup).toContain("OpenAI proposed payment-method update");
    expect(markup).not.toContain("Razorpay state reconciled");
    expect(markup).not.toContain("AI Proposed Create Recovery Link");
  });
});

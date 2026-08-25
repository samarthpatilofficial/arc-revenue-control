import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { ApprovalQueue } from "../features/approvals/ApprovalsPage";
import { DecisionIntelligence } from "../features/cases/DecisionIntelligence";
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
    reason_code: "RECOVERY_LINK_APPROPRIATE",
    explanation: "A bounded recovery path is appropriate.",
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
  });

  it("renders a synthetic approval without implying provider evidence", () => {
    const approval: ApprovalQueueItem = {
      approval_request_id: "approval-test",
      case_reference: "demo_high_value_approval_v1",
      amount_minor: 2_500_000,
      currency: "INR",
      strategy_action: "CREATE_RECOVERY_LINK",
      strategy_provenance: "OFFLINE_SIMULATION",
      policy_reason_code: "HIGH_VALUE_APPROVAL_REQUIRED",
      approval_status: "PENDING",
      requested_at: "2026-08-23T12:00:00Z",
      decided_at: null,
      data_origin: "SYNTHETIC_DEMO",
    };
    const markup = renderToStaticMarkup(
      <MemoryRouter><ApprovalQueue approvals={[approval]} /></MemoryRouter>,
    );
    expect(markup).toContain("₹25,000.00");
    expect(markup).toContain("Synthetic Demo");
    expect(markup).toContain("Pending");
    expect(markup).not.toContain("Test Mode");
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
});

import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { CaseStoryBanner } from "../cases/CaseStoryBanner";
import { caseStoryBanner } from "../cases/storyBannerRules";
import type { CaseDetail, CaseListItem } from "../../types/api";
import { DemoStories } from "./DemoStories";
import { detectDemoStories } from "./storyDetection";

function caseItem(overrides: Partial<CaseListItem>): CaseListItem {
  return {
    case_reference: "case_fixture",
    amount_minor: 1_000,
    currency: "INR",
    current_state: "DETECTED",
    resolution_kind: "PENDING",
    payment_method: "card",
    failure_category: "CUSTOMER_AUTHENTICATION",
    recovery_disposition: "CUSTOMER_ACTION_REQUIRED",
    eligibility_status: "ELIGIBLE",
    detected_at: "2026-08-23T12:00:00Z",
    resolved_at: null,
    strategy_action: null,
    strategy_provenance: "BYPASSED",
    policy_result: null,
    approval_status: null,
    recovery_execution_status: null,
    outcome_status: null,
    recovered_amount_minor: null,
    provider_mode: null,
    data_origin: null,
    ...overrides,
  };
}

const realRecovery = caseItem({
  case_reference: "case_real_recovery",
  data_origin: "TEST_MODE",
  current_state: "RECOVERED",
  resolution_kind: "ARC_RECOVERED",
  strategy_provenance: "DETERMINISTIC_RULE",
  recovered_amount_minor: 1_000,
  provider_mode: "TEST",
  outcome_status: "RECOVERED",
  recovery_execution_status: "SUCCEEDED",
});
const highValue = caseItem({
  case_reference: "case_high_value",
  amount_minor: 2_500_000,
  data_origin: "SYNTHETIC_DEMO",
  current_state: "POLICY_VALIDATED",
  resolution_kind: "REQUIRES_APPROVAL",
  strategy_action: "CREATE_RECOVERY_LINK",
  strategy_provenance: "OFFLINE_SIMULATION",
  policy_result: "REQUIRES_APPROVAL",
  approval_status: "PENDING",
});
const alreadyCaptured = caseItem({
  case_reference: "case_already_captured",
  amount_minor: 75_000,
  data_origin: "SYNTHETIC_DEMO",
  current_state: "RECOVERED",
  resolution_kind: "ALREADY_CAPTURED",
});
const hardStop = caseItem({
  case_reference: "case_hard_stop",
  amount_minor: 180_000,
  data_origin: "SYNTHETIC_DEMO",
  current_state: "EXHAUSTED",
  resolution_kind: "EXHAUSTED",
  strategy_action: "CREATE_RECOVERY_LINK",
  strategy_provenance: "OFFLINE_SIMULATION",
  policy_result: "BLOCKED",
});
const allCases = [realRecovery, highValue, alreadyCaptured, hardStop];

function detail(overrides: Partial<CaseDetail>): CaseDetail {
  const base: CaseDetail = {
    data_origin: "SYNTHETIC_DEMO",
    case: {
      case_reference: "case_detail_fixture",
      amount_minor: 1_000,
      currency: "INR",
      current_state: "DETECTED",
      resolution_kind: "PENDING",
      payment_method: "card",
      attempt_count: 0,
      contact_attempt_count: 0,
      detected_at: "2026-08-23T12:00:00Z",
      resolved_at: null,
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
  return { ...base, ...overrides };
}

describe("semantic demo stories", () => {
  it("detects the genuine Test Mode attributed recovery", () => {
    const story = detectDemoStories(allCases).find((item) => item.key === "realRecovery");
    expect(story?.caseItem?.case_reference).toBe("case_real_recovery");
    expect(story?.amountMinor).toBe(1_000);
  });

  it("detects the pending high-value policy approval", () => {
    const story = detectDemoStories(allCases).find((item) => item.key === "highValueApproval");
    expect(story?.caseItem?.case_reference).toBe("case_high_value");
  });

  it("detects already-captured protection without attribution", () => {
    const story = detectDemoStories(allCases).find((item) => item.key === "alreadyCaptured");
    expect(story?.caseItem?.case_reference).toBe("case_already_captured");
  });

  it("detects a terminal hard stop without execution", () => {
    const story = detectDemoStories(allCases).find((item) => item.key === "hardStop");
    expect(story?.caseItem?.case_reference).toBe("case_hard_stop");
  });

  it("renders an explicit unavailable state instead of fake data", () => {
    const markup = renderToStaticMarkup(
      <MemoryRouter><DemoStories stories={detectDemoStories([])} /></MemoryRouter>,
    );
    expect(markup.match(/Scenario unavailable/g)).toHaveLength(4);
    expect(markup).not.toContain("₹");
  });

  it("never confuses genuine Test Mode and synthetic story origins", () => {
    const stories = detectDemoStories(allCases);
    const realStory = stories.find((item) => item.key === "realRecovery");
    expect(realStory).toBeDefined();
    const realMarkup = renderToStaticMarkup(
      <MemoryRouter><DemoStories stories={[realStory!]} /></MemoryRouter>,
    );
    expect(realMarkup).toContain("Test Mode");
    expect(realMarkup).not.toContain("Synthetic Demo");

    for (const syntheticStory of stories.filter((item) => item.key !== "realRecovery")) {
      const markup = renderToStaticMarkup(
        <MemoryRouter><DemoStories stories={[syntheticStory]} /></MemoryRouter>,
      );
      expect(markup).toContain("Synthetic Demo");
      expect(markup).not.toContain("Test Mode");
    }
  });
});

describe("evidence-derived case banners", () => {
  it("selects each banner only from its supporting case state", () => {
    const recovered = detail({
      data_origin: "TEST_MODE",
      case: { ...detail({}).case, current_state: "RECOVERED", resolution_kind: "ARC_RECOVERED" },
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
    });
    const approval = detail({
      policy: {
        result: "REQUIRES_APPROVAL",
        reason_code: "HIGH_VALUE_APPROVAL_REQUIRED",
        explanation: "Approval required.",
        approval_threshold_minor: 2_500_000,
        evaluated_at: "2026-08-23T12:03:00Z",
      },
      approval: {
        approval_request_id: "approval-fixture",
        approval_status: "PENDING",
        requested_at: "2026-08-23T12:04:00Z",
        decided_at: null,
      },
    });
    const captured = detail({
      case: { ...detail({}).case, current_state: "RECOVERED", resolution_kind: "ALREADY_CAPTURED" },
    });
    const stopped = detail({
      case: { ...detail({}).case, current_state: "EXHAUSTED", resolution_kind: "EXHAUSTED" },
    });

    expect(caseStoryBanner(recovered)?.title).toBe("Recovery verified by provider evidence");
    expect(caseStoryBanner(approval)?.title).toBe("Human authority required");
    expect(caseStoryBanner(captured)?.title).toBe("No intervention required");
    expect(caseStoryBanner(stopped)?.title).toBe("Automation stopped safely");
    expect(caseStoryBanner(detail({}))).toBeNull();

    const markup = renderToStaticMarkup(<CaseStoryBanner detail={recovered} />);
    expect(markup).toContain("Razorpay Test Mode provider evidence");
    expect(markup).toContain("Evidence-backed Attribution");
  });
});

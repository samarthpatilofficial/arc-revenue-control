import type { CaseListItem } from "../../types/api";

export type DemoStoryKey =
  | "realRecovery"
  | "highValueApproval"
  | "alreadyCaptured"
  | "hardStop";

export interface DemoStory {
  key: DemoStoryKey;
  title: string;
  explanation: string;
  authority: string;
  caseItem: CaseListItem | null;
  amountMinor: number | null;
  currency: string | null;
}

const STORY_COPY: Readonly<
  Record<DemoStoryKey, Omit<DemoStory, "key" | "caseItem" | "amountMinor" | "currency">>
> = {
  realRecovery: {
    title: "Recovery verified",
    explanation: "Recovery verified by Razorpay Test Mode provider evidence and ARC attribution.",
    authority: "EVIDENCE_BACKED_ATTRIBUTION",
  },
  highValueApproval: {
    title: "Human approval required",
    explanation: "An offline strategy simulation proposed recovery; policy retained financial authority.",
    authority: "DETERMINISTIC_POLICY",
  },
  alreadyCaptured: {
    title: "Duplicate recovery prevented",
    explanation: "Authoritative payment truth showed the revenue was already captured.",
    authority: "AUTHORITATIVE_RECONCILIATION",
  },
  hardStop: {
    title: "Automation stopped safely",
    explanation: "Deterministic controls prevented another recovery action.",
    authority: "DETERMINISTIC_POLICY",
  },
};

function highestValue(
  cases: CaseListItem[],
  predicate: (item: CaseListItem) => boolean,
  value: (item: CaseListItem) => number | null,
): CaseListItem | null {
  return cases.filter(predicate).sort((left, right) => {
    const amountDifference = (value(right) ?? -1) - (value(left) ?? -1);
    if (amountDifference !== 0) return amountDifference;
    return right.detected_at.localeCompare(left.detected_at);
  })[0] ?? null;
}

function story(
  key: DemoStoryKey,
  caseItem: CaseListItem | null,
  amountMinor: number | null,
): DemoStory {
  return {
    key,
    ...STORY_COPY[key],
    caseItem,
    amountMinor,
    currency: caseItem?.currency ?? null,
  };
}

export function detectDemoStories(cases: CaseListItem[]): DemoStory[] {
  const realRecovery = highestValue(
    cases,
    (item) =>
      item.data_origin === "TEST_MODE" &&
      item.resolution_kind === "ARC_RECOVERED" &&
      item.recovered_amount_minor !== null &&
      item.recovered_amount_minor > 0,
    (item) => item.recovered_amount_minor,
  );
  const highValueApproval = highestValue(
    cases,
    (item) =>
      item.data_origin === "SYNTHETIC_DEMO" &&
      item.policy_result === "REQUIRES_APPROVAL" &&
      item.approval_status === "PENDING",
    (item) => item.amount_minor,
  );
  const alreadyCaptured = highestValue(
    cases,
    (item) =>
      item.data_origin === "SYNTHETIC_DEMO" &&
      item.resolution_kind === "ALREADY_CAPTURED" &&
      item.strategy_action === null &&
      item.recovered_amount_minor === null,
    (item) => item.amount_minor,
  );
  const hardStop = highestValue(
    cases,
    (item) =>
      item.data_origin === "SYNTHETIC_DEMO" &&
      (item.resolution_kind === "EXHAUSTED" || item.resolution_kind === "ESCALATED") &&
      item.recovery_execution_status === null,
    (item) => item.amount_minor,
  );

  return [
    story(
      "realRecovery",
      realRecovery,
      realRecovery?.recovered_amount_minor ?? null,
    ),
    story(
      "highValueApproval",
      highValueApproval,
      highValueApproval?.amount_minor ?? null,
    ),
    story(
      "alreadyCaptured",
      alreadyCaptured,
      alreadyCaptured?.amount_minor ?? null,
    ),
    story("hardStop", hardStop, hardStop?.amount_minor ?? null),
  ];
}

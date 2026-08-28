import type { DataOrigin, StrategyProvenance, TimelineItem } from "../types/api";

const DISPLAY_LABELS: Readonly<Record<string, string>> = {
  ARC_CONTROL_PLANE: "ARC Control Plane",
  AUTHORITATIVE_RECONCILIATION: "Authoritative Reconciliation",
  DETERMINISTIC_PRECONDITIONS: "Deterministic Preconditions",
  DETERMINISTIC_DIAGNOSIS: "Deterministic Diagnosis",
  DETERMINISTIC_RULE: "Deterministic Rule",
  DETERMINISTIC_POLICY: "Deterministic Policy",
  HUMAN_APPROVAL: "Human Approval",
  GOVERNED_EXECUTOR: "Governed Executor",
  AUTHORITATIVE_PROVIDER_EVIDENCE: "Provider Evidence",
  EVIDENCE_BACKED_ATTRIBUTION: "Evidence-backed Attribution",
  CONTROLLED_SIMULATION: "Controlled Simulation",
  CONTROLLED_SYNTHETIC_INPUT: "Controlled Synthetic Input",
  OPENAI_STRATEGY: "OpenAI Strategy",
  TEST_MODE: "Test Mode",
  LIVE_MODE: "Live Mode",
  SYNTHETIC_DEMO: "Synthetic Demo",
  SYNTHETIC_INPUT: "Synthetic Input",
  ARC_RECOVERED: "Recovered",
  ALREADY_CAPTURED: "Already Captured",
  AWAITING_OUTCOME: "Awaiting Outcome",
  OFFLINE_SIMULATION: "Offline Simulation",
  OPENAI: "OpenAI",
  BYPASSED: "Bypassed",
  NO_ACTION: "No action",
  WAIT: "Wait",
  REQUEST_RETRY: "Request retry",
  CREATE_RECOVERY_LINK: "Create recovery link",
  REQUEST_PAYMENT_METHOD_UPDATE: "Request payment method update",
  ESCALATE_TO_HUMAN: "Escalate to human",
  REQUIRES_APPROVAL: "Requires approval",
  WAITING_FOR_OUTCOME: "Waiting for outcome",
  STRUCTURED_REASON_INSUFFICIENT_FUNDS: "Insufficient funds",
  STRUCTURED_REASON_INCORRECT_OTP: "Incorrect OTP",
  STOPPING_RULE_REQUIRES_APPROVAL: "Approval required by policy",
  AMOUNT_REQUIRES_HUMAN_APPROVAL: "High-value amount requires approval",
  MAX_AUTOMATED_ATTEMPTS_REACHED: "Maximum automated attempts reached",
  ARC_PAYMENT_LINK_CAPTURED: "Provider payment captured",
};

export function strategyProvenanceLabel(value: string): string {
  return {
    DETERMINISTIC_RULE: "Deterministic",
    OFFLINE_SIMULATION: "Offline Simulation",
    OPENAI: "OpenAI",
    BYPASSED: "Bypassed — not required",
  }[value] ?? displayEnum(value);
}

export function displayEnum(value: string | null | undefined): string {
  if (!value) {
    return "Not available";
  }
  const known = DISPLAY_LABELS[value];
  if (known) {
    return known;
  }
  return value
    .toLowerCase()
    .split("_")
    .filter(Boolean)
    .map((word) => {
      if (word === "ai") return "AI";
      if (word === "arc") return "ARC";
      if (word === "otp") return "OTP";
      return word[0]?.toUpperCase() + word.slice(1);
    })
    .join(" ");
}

export function authorityLabel(value: string | null): string {
  return value ? (DISPLAY_LABELS[value] ?? displayEnum(value)) : "Recorded authority";
}

export function displayDetail(value: string): string {
  return value
    .split(" / ")
    .map((segment) => displayEnum(segment))
    .join(" / ");
}

export function displayStrategyReason(
  reasonCode: string,
  provenance: StrategyProvenance,
  dataOrigin: DataOrigin | null,
): string {
  if (reasonCode === "AI_PROPOSED_CREATE_RECOVERY_LINK") {
    if (provenance === "OFFLINE_SIMULATION") {
      return "Offline simulation proposed recovery link";
    }
    if (provenance === "OPENAI") {
      return "OpenAI proposed recovery link";
    }
  }
  if (
    reasonCode === "AI_PROPOSED_PAYMENT_METHOD_UPDATE" &&
    provenance === "OPENAI"
  ) {
    return "OpenAI proposed payment-method update";
  }
  if (
    reasonCode === "SYNTHETIC_EXECUTION_TEST" &&
    provenance === "DETERMINISTIC_RULE" &&
    dataOrigin === "TEST_MODE"
  ) {
    return "Controlled Test Mode recovery strategy";
  }
  return displayEnum(reasonCode);
}

export function displayStrategyExplanation(
  explanation: string,
  reasonCode: string,
  provenance: StrategyProvenance,
  dataOrigin: DataOrigin | null,
): string {
  if (
    explanation === "Synthetic bounded execution test proposal." &&
    reasonCode === "SYNTHETIC_EXECUTION_TEST" &&
    provenance === "DETERMINISTIC_RULE" &&
    dataOrigin === "TEST_MODE"
  ) {
    return "Controlled Test Mode recovery action proposed.";
  }
  return explanation;
}

export function displayTimelineTitle(item: TimelineItem): string {
  if (item.stage === "RECONCILED") {
    return item.data_origin === "TEST_MODE"
      ? "Razorpay Test Mode state reconciled"
      : "Controlled payment state reconciled";
  }
  if (
    item.stage === "DEMO" &&
    item.title === "Synthetic demo scenario seeded"
  ) {
    return "Synthetic scenario initialized";
  }
  return item.title;
}

export function displayTimelineDetail(item: TimelineItem): string | null {
  if (!item.detail) {
    return null;
  }
  if (item.stage === "STRATEGY" && item.strategy_provenance) {
    return displayStrategyReason(
      item.detail,
      item.strategy_provenance,
      item.data_origin,
    );
  }
  return displayDetail(item.detail);
}

export function shortReference(value: string): string {
  if (value.length <= 24) {
    return value;
  }
  return `${value.slice(0, 13)}…${value.slice(-7)}`;
}

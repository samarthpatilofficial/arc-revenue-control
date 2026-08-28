import { displayEnum } from "./display";
import type { CaseListItem } from "../types/api";

export function caseContextLabel(item: CaseListItem): string {
  if (item.data_origin === "TEST_MODE" && item.resolution_kind === "ARC_RECOVERED") {
    return "Provider-verified recovery";
  }
  if (item.resolution_kind === "ALREADY_CAPTURED") {
    return "Already captured — no action";
  }
  if (
    item.data_origin === "SYNTHETIC_INPUT" &&
    item.strategy_provenance === "OPENAI" &&
    item.strategy_action === "REQUEST_PAYMENT_METHOD_UPDATE"
  ) {
    return "OpenAI payment-method update";
  }
  if (
    item.data_origin === "SYNTHETIC_DEMO" &&
    item.strategy_provenance === "OFFLINE_SIMULATION" &&
    item.strategy_action === "CREATE_RECOVERY_LINK" &&
    item.policy_result === "REQUIRES_APPROVAL" &&
    item.approval_status === "PENDING"
  ) {
    return "High-value recovery link";
  }
  if (item.policy_result === "REQUIRES_APPROVAL") {
    return "Human approval required";
  }
  if (item.resolution_kind === "EXHAUSTED") {
    return "Automation stopped safely";
  }
  if (item.resolution_kind === "ESCALATED") {
    return "Escalated for review";
  }
  if (item.strategy_action) {
    return displayEnum(item.strategy_action);
  }
  if (item.failure_category) {
    return `${displayEnum(item.failure_category)} case`;
  }
  return "Recovery case";
}

export function approvalContextLabel(item: {
  data_origin: string | null;
  strategy_provenance: string;
  strategy_action: string;
}): string {
  if (
    item.data_origin === "SYNTHETIC_INPUT" &&
    item.strategy_provenance === "OPENAI" &&
    item.strategy_action === "REQUEST_PAYMENT_METHOD_UPDATE"
  ) {
    return "OpenAI payment-method update";
  }
  if (
    item.data_origin === "SYNTHETIC_DEMO" &&
    item.strategy_provenance === "OFFLINE_SIMULATION" &&
    item.strategy_action === "CREATE_RECOVERY_LINK"
  ) {
    return "High-value recovery link";
  }
  return "Human approval required";
}

export function caseDiagnosisLabel(item: CaseListItem): string {
  return item.resolution_kind === "ALREADY_CAPTURED"
    ? "Not required"
    : displayEnum(item.failure_category);
}

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
    item.case_reference === "openai_evidence_high_value_v1" &&
    item.data_origin === "SYNTHETIC_INPUT" &&
    item.strategy_provenance === "OPENAI" &&
    item.strategy_action === "REQUEST_PAYMENT_METHOD_UPDATE"
  ) {
    return "OpenAI payment-method update";
  }
  if (
    item.case_reference === "demo_high_value_approval_v1" &&
    item.data_origin === "SYNTHETIC_DEMO" &&
    item.strategy_action === "CREATE_RECOVERY_LINK"
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

import type { CaseDetail } from "../types/api";

export function detailTitle(detail: CaseDetail): string {
  if (
    detail.data_origin === "TEST_MODE" &&
    detail.case.resolution_kind === "ARC_RECOVERED"
  ) {
    return "Provider-verified recovery";
  }
  if (detail.case.resolution_kind === "ALREADY_CAPTURED") {
    return "Already captured — no action";
  }
  if (
    detail.data_origin === "SYNTHETIC_INPUT" &&
    detail.strategy?.provenance === "OPENAI" &&
    detail.strategy.action === "REQUEST_PAYMENT_METHOD_UPDATE" &&
    detail.approval?.approval_status === "PENDING"
  ) {
    return "OpenAI payment-method update";
  }
  if (
    detail.case.resolution_kind === "REQUIRES_APPROVAL" ||
    detail.approval?.approval_status === "PENDING"
  ) {
    return "Human approval required";
  }
  if (detail.case.resolution_kind === "EXHAUSTED") {
    return "Automation stopped safely";
  }
  if (detail.case.resolution_kind === "ESCALATED") {
    return "Escalated for review";
  }
  return "Recovery case";
}

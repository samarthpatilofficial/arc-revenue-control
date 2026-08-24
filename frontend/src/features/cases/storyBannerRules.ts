import {
  AlertTriangle,
  CheckCircle2,
  SearchCheck,
  ShieldCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { CaseDetail } from "../../types/api";

export interface CaseStoryBannerSpec {
  title: string;
  message: string;
  authority: string;
  tone: "success" | "warning" | "info" | "danger";
  icon: LucideIcon;
}

export function caseStoryBanner(detail: CaseDetail): CaseStoryBannerSpec | null {
  if (
    detail.data_origin === "TEST_MODE" &&
    detail.case.current_state === "RECOVERED" &&
    detail.attribution?.provider_mode === "TEST" &&
    detail.outcome?.provider_mode === "TEST" &&
    detail.outcome.outcome_status === "RECOVERED"
  ) {
    return {
      title: "Recovery independently verified",
      message: "Razorpay Test Mode provider evidence confirms captured payment and evidence-backed ARC attribution.",
      authority: "EVIDENCE_BACKED_ATTRIBUTION",
      tone: "success",
      icon: CheckCircle2,
    };
  }
  if (
    detail.policy?.result === "REQUIRES_APPROVAL" &&
    detail.approval?.approval_status === "PENDING"
  ) {
    return {
      title: "Human authority required",
      message: "ARC cannot execute this recovery until the policy-scoped approval is resolved.",
      authority: "HUMAN_APPROVAL",
      tone: "warning",
      icon: ShieldCheck,
    };
  }
  if (
    detail.case.current_state === "RECOVERED" &&
    detail.attribution === null &&
    detail.execution === null
  ) {
    return {
      title: "No intervention required",
      message: "Authoritative reconciliation found that the payment was already captured.",
      authority: "AUTHORITATIVE_RECONCILIATION",
      tone: "info",
      icon: SearchCheck,
    };
  }
  if (
    (detail.case.current_state === "EXHAUSTED" ||
      detail.case.current_state === "ESCALATED") &&
    detail.execution === null
  ) {
    return {
      title: "Automation stopped safely",
      message: "Deterministic controls prevented an additional external recovery action.",
      authority: "DETERMINISTIC_POLICY",
      tone: "danger",
      icon: AlertTriangle,
    };
  }
  return null;
}

import { FlaskConical, Radio, ShieldCheck } from "lucide-react";
import { authorityLabel, displayEnum } from "../lib/display";
import type { DataOrigin } from "../types/api";

type BadgeTone = "neutral" | "success" | "warning" | "danger" | "info";

const SUCCESS_VALUES = new Set([
  "RECOVERED",
  "SUCCEEDED",
  "AUTHORIZED",
  "APPROVED",
  "ELIGIBLE",
  "complete",
]);
const WARNING_VALUES = new Set([
  "PENDING",
  "WAIT",
  "WAITING_FOR_OUTCOME",
  "REQUIRES_APPROVAL",
  "REVIEW",
  "pending",
]);
const DANGER_VALUES = new Set([
  "BLOCKED",
  "FAILED",
  "EXHAUSTED",
  "ESCALATED",
  "REJECTED",
  "REVIEW_REQUIRED",
  "COMPENSATION_REQUIRED",
  "blocked",
]);
const INFO_VALUES = new Set([
  "DETECTED",
  "RECONCILING",
  "DIAGNOSED",
  "DECISIONED",
  "POLICY_VALIDATED",
  "ACTIONED",
  "IN_PROGRESS",
]);

function toneFor(value: string): BadgeTone {
  if (SUCCESS_VALUES.has(value)) return "success";
  if (WARNING_VALUES.has(value)) return "warning";
  if (DANGER_VALUES.has(value)) return "danger";
  if (INFO_VALUES.has(value)) return "info";
  return "neutral";
}

export function StatusBadge({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="muted">—</span>;
  const tone = toneFor(value);
  return <span className={`badge badge-${tone}`}>{displayEnum(value)}</span>;
}

export function OriginBadge({ origin }: { origin: DataOrigin | null }) {
  if (!origin) return <span className="badge">Origin unavailable</span>;
  const details = {
    TEST_MODE: {
      className: "badge-origin-test",
      title: "Razorpay Test Mode — no live money",
      icon: <FlaskConical size={12} aria-hidden="true" />,
    },
    SYNTHETIC_DEMO: {
      className: "badge-origin-synthetic",
      title: "Controlled synthetic scenario — not provider evidence",
      icon: <ShieldCheck size={12} aria-hidden="true" />,
    },
    LIVE_MODE: {
      className: "badge-origin-live",
      title: "Live provider mode",
      icon: <Radio size={12} aria-hidden="true" />,
    },
  }[origin];
  return (
    <span className={`badge ${details.className}`} title={details.title}>
      {details.icon}
      {displayEnum(origin)}
    </span>
  );
}

export function AuthorityBadge({ authority }: { authority: string | null }) {
  return (
    <span className="badge authority-badge">
      {authorityLabel(authority)}
    </span>
  );
}

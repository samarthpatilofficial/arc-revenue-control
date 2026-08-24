import {
  Bot,
  CheckCircle2,
  CircleDollarSign,
  Eye,
  Gauge,
  Hourglass,
  Landmark,
  SearchCheck,
  ShieldCheck,
  Siren,
  Users,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { CaseTable } from "../../components/CaseTable";
import { EmptyState, ErrorState, MetricSkeletons, TableSkeleton } from "../../components/Feedback";
import { PageHeader, SectionCard } from "../../components/Layout";
import { MetricCard } from "../../components/MetricCard";
import { OriginBadge, StatusBadge } from "../../components/Badges";
import { getCases, getDashboardSummary } from "../../lib/api";
import { formatMoney, formatPercent } from "../../lib/format";
import { useApiResource } from "../../lib/useApiResource";
import type { CaseListItem, DashboardSummary } from "../../types/api";

interface OverviewData {
  summary: DashboardSummary;
  cases: CaseListItem[];
}

function loadOverview(signal: AbortSignal): Promise<OverviewData> {
  return Promise.all([
    getDashboardSummary(signal),
    getCases({ limit: 50 }, signal),
  ]).then(([summary, cases]) => ({ summary, cases }));
}

const attentionStates = new Set(["ESCALATED", "EXHAUSTED", "POLICY_VALIDATED"]);

function priorityCases(cases: CaseListItem[]): CaseListItem[] {
  return [...cases]
    .sort((left, right) => {
      const leftAttention = attentionStates.has(left.current_state) ? 1 : 0;
      const rightAttention = attentionStates.has(right.current_state) ? 1 : 0;
      if (leftAttention !== rightAttention) return rightAttention - leftAttention;
      return (right.amount_minor ?? -1) - (left.amount_minor ?? -1);
    })
    .slice(0, 6);
}

const controlSteps: Array<{
  label: string;
  note: string;
  icon: LucideIcon;
  className?: string;
}> = [
  { label: "Detect", note: "Risk signal", icon: Gauge },
  { label: "Reconcile", note: "Payment truth", icon: SearchCheck },
  { label: "Diagnose", note: "Failure context", icon: Wrench },
  { label: "Decide", note: "AI proposal", icon: Bot, className: "ai" },
  { label: "Authorize", note: "Policy authority", icon: ShieldCheck, className: "policy" },
  { label: "Execute", note: "Governed action", icon: Landmark },
  { label: "Observe", note: "Provider evidence", icon: Eye, className: "evidence" },
  { label: "Measure", note: "Attribution", icon: CircleDollarSign },
];

export function OverviewPage() {
  const resource = useApiResource(loadOverview);

  if (resource.error) {
    return (
      <>
        <PageHeader
          title="Revenue Recovery"
          subtitle="Policy-governed recovery intelligence for failed payments."
        />
        <SectionCard><ErrorState onRetry={resource.retry} /></SectionCard>
      </>
    );
  }

  const summary = resource.data?.summary;
  const cases = resource.data?.cases ?? [];
  const recoveredProof = cases.find(
    (item) =>
      item.data_origin === "TEST_MODE" &&
      item.current_state === "RECOVERED" &&
      item.recovered_amount_minor !== null &&
      item.recovered_amount_minor > 0,
  );

  return (
    <>
      <PageHeader
        title="Revenue Recovery"
        subtitle="Policy-governed recovery intelligence for failed payments."
        actions={<span className="badge badge-info">Read-only operations</span>}
      />

      {resource.loading || !summary ? (
        <MetricSkeletons />
      ) : (
        <div className="metrics-grid">
          <MetricCard
            label="Revenue at Risk"
            value={formatMoney(summary.revenue_at_risk_minor, summary.currency)}
            caption="Evidence-scoped evaluated revenue"
            icon={Siren}
          />
          <MetricCard
            label="Recovered Revenue"
            value={formatMoney(summary.recovered_revenue_minor, summary.currency)}
            caption="Provider-evidence attribution only"
            icon={CircleDollarSign}
          />
          <MetricCard
            label="Recovery Rate"
            value={formatPercent(summary.recovery_rate_by_amount)}
            caption="Recovered amount / revenue at risk"
            icon={Gauge}
          />
          <MetricCard
            label="Recovered Cases"
            value={String(summary.recovered_cases)}
            caption={`${formatPercent(summary.recovery_rate_by_cases)} of evaluated cases`}
            icon={CheckCircle2}
          />
          <MetricCard
            label="Awaiting Outcome"
            value={String(summary.awaiting_outcome)}
            caption="Provider outcome still pending"
            icon={Hourglass}
          />
          <MetricCard
            label="Requires Attention"
            value={String(summary.requires_attention)}
            caption="Review-required provider outcomes"
            icon={Users}
          />
        </div>
      )}

      <div className={`overview-layout ${!resource.loading && !recoveredProof ? "control-loop-only" : ""}`}>
        <SectionCard
          title="Recovery control loop"
          subtitle="Financial truth and authority remain deterministic around one bounded AI stage."
        >
          <div className="control-loop" aria-label="ARC recovery control loop">
            {controlSteps.map(({ label, note, icon: Icon, className }) => (
              <div className={`control-step ${className ?? ""}`} key={label}>
                <span className="control-step-icon">
                  <Icon size={16} strokeWidth={1.8} aria-hidden="true" />
                </span>
                <strong>{label}</strong>
                <small>{note}</small>
              </div>
            ))}
          </div>
        </SectionCard>

        {resource.loading ? (
          <div className="skeleton" style={{ minHeight: 195 }} />
        ) : recoveredProof ? (
          <Link
            className="proof-card"
            to={`/cases/${encodeURIComponent(recoveredProof.case_reference)}`}
          >
            <div className="proof-eyebrow">
              <CheckCircle2 size={15} aria-hidden="true" /> Recovery verified
            </div>
            <div className="proof-amount">
              {formatMoney(
                recoveredProof.recovered_amount_minor,
                recoveredProof.currency,
              )}
            </div>
            <p className="proof-description">
              Captured through ARC-governed recovery
            </p>
            <div className="proof-meta">
              <OriginBadge origin={recoveredProof.data_origin} />
              <StatusBadge value={recoveredProof.current_state} />
            </div>
          </Link>
        ) : null}
      </div>

      <SectionCard
        className="table-card"
        title="Attention & recent cases"
        subtitle="Prioritized from current persisted recovery state."
        headerAction={<Link className="button button-secondary" to="/cases">View all cases</Link>}
      >
        {resource.loading ? (
          <TableSkeleton />
        ) : cases.length ? (
          <CaseTable cases={priorityCases(cases)} compact />
        ) : (
          <EmptyState
            title="No recovery cases available"
            message="Cases will appear after accepted events are reconciled."
          />
        )}
      </SectionCard>
    </>
  );
}

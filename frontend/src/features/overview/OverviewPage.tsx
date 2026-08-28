import {
  Bot,
  CheckCircle2,
  CircleDollarSign,
  Eye,
  FlaskConical,
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
import { Link, useOutletContext } from "react-router-dom";
import { CaseTable } from "../../components/CaseTable";
import { EmptyState, ErrorState, MetricSkeletons, TableSkeleton } from "../../components/Feedback";
import { PageHeader, SectionCard } from "../../components/Layout";
import { MetricCard } from "../../components/MetricCard";
import { StatusBadge } from "../../components/Badges";
import { getCases, getDashboardSummary, getEvaluationSummary } from "../../lib/api";
import type { ApiHealthState } from "../../lib/backendHealth";
import { formatMoney, formatPercent } from "../../lib/format";
import { useApiResource } from "../../lib/useApiResource";
import type { CaseListItem, DashboardSummary, EvaluationSummary } from "../../types/api";
import { DemoStories } from "./DemoStories";
import { detectDemoStories } from "./storyDetection";

interface OverviewData {
  summary: DashboardSummary;
  cases: CaseListItem[];
  evaluation: EvaluationSummary;
}

function loadOverview(signal: AbortSignal): Promise<OverviewData> {
  return Promise.all([
    getDashboardSummary(signal),
    getCases({ limit: 50 }, signal),
    getEvaluationSummary(signal),
  ]).then(([summary, cases, evaluation]) => ({ summary, cases, evaluation }));
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
  { label: "Reconcile", note: "Provider truth", icon: SearchCheck },
  { label: "Diagnose", note: "Failure context", icon: Wrench },
  { label: "Decide", note: "Bounded AI strategy", icon: Bot, className: "ai" },
  { label: "Authorize", note: "Policy / human authority", icon: ShieldCheck, className: "policy" },
  { label: "Execute", note: "Governed action", icon: Landmark },
  { label: "Observe", note: "Provider evidence", icon: Eye, className: "evidence" },
  { label: "Measure", note: "Recovery attribution", icon: CircleDollarSign },
];

export function EvidenceClasses({
  evaluation,
  recoveredProof,
}: {
  evaluation: EvaluationSummary;
  recoveredProof: CaseListItem | null;
}) {
  return (
    <div className="evidence-class-grid">
      <article className="evidence-class-card provider-proof">
        <div className="evidence-class-eyebrow">
          <CheckCircle2 size={16} aria-hidden="true" /> Provider-verified Test Mode recovery
        </div>
        {recoveredProof ? (
          <Link
            className="proof-card"
            to={`/cases/${encodeURIComponent(recoveredProof.case_reference)}`}
          >
            <div className="proof-content">
              <div className="proof-label">Provider-verified recovery</div>
              <div className="proof-amount">
                {formatMoney(
                  recoveredProof.recovered_amount_minor,
                  recoveredProof.currency,
                )}
              </div>
              <div className="proof-status"><StatusBadge value="RECOVERED" /></div>
              <p className="proof-description">Captured-payment evidence validates this Test Mode recovery.</p>
            </div>
            <div className="proof-evidence">
              <strong>Evidence chain</strong>
              <span><CheckCircle2 size={14} aria-hidden="true" /> Razorpay Test Mode</span>
              <span><CheckCircle2 size={14} aria-hidden="true" /> Deterministic Test Strategy</span>
              <span><CheckCircle2 size={14} aria-hidden="true" /> Evidence-backed ARC attribution</span>
              <span className="proof-action">View recovery trace</span>
            </div>
          </Link>
        ) : (
          <p className="muted">Provider-backed recovery proof is unavailable.</p>
        )}
      </article>

      <article className="evidence-class-card batch-proof">
        <div className="evidence-class-eyebrow">
          <FlaskConical size={15} aria-hidden="true" /> Synthetic batch evaluation
        </div>
        <div className="batch-primary-grid">
          <span><strong>{evaluation.metrics.cases_evaluated}</strong> cases evaluated</span>
          <span><strong>{formatMoney(evaluation.metrics.revenue_at_risk_minor, "INR")}</strong> revenue at risk</span>
          <span><strong>{formatMoney(evaluation.metrics.synthetic_recovered_amount_minor, "INR")}</strong> synthetic recovered</span>
          <span><strong>{evaluation.metrics.synthetic_recovered_cases}</strong> recovered cases</span>
        </div>
        <div className="batch-proof-grid">
          <span><strong>{evaluation.metrics.automated_actions_authorized}</strong> automated authorizations</span>
          <span><strong>{evaluation.metrics.human_approval_required}</strong> human approvals</span>
          <span><strong>{evaluation.metrics.safe_stop_cases}</strong> safe stops</span>
          <span><strong>{evaluation.metrics.already_captured_protected}</strong> current-state protections</span>
        </div>
        <div className="batch-context-row">
          <span>{formatMoney(evaluation.metrics.revenue_evaluated_minor, "INR")} total evaluated</span>
          <span>{evaluation.metrics.wait_cases} safe waits</span>
        </div>
        <div className="safety-integrity-row" aria-label="Synthetic evaluation safety integrity">
          <span><strong>{evaluation.metrics.policy_violations_executed}</strong> policy violations</span>
          <span><strong>{evaluation.metrics.unsafe_actions_after_capture}</strong> unsafe post-capture actions</span>
          <span><strong>{evaluation.metrics.duplicate_executions}</strong> duplicate executions</span>
          <span className="prevented"><strong>{evaluation.metrics.duplicate_actions_prevented}</strong> duplicates prevented</span>
        </div>
        <p className="evidence-disclaimer">
          Synthetic evaluation results are controlled test evidence, not merchant revenue, and never enter provider-backed recovery metrics.
        </p>
      </article>
    </div>
  );
}

export function OverviewLoadFailure({
  healthState,
  onRetry,
}: {
  healthState: ApiHealthState;
  onRetry: () => void;
}) {
  const backendIsWaking = healthState === "checking" || healthState === "waking";
  return (
    <SectionCard>
      <ErrorState
        {...(backendIsWaking
          ? {
              title: "Demo backend is waking up",
              message:
                "Demo backend is waking up. This can take up to a minute on the free evaluator deployment.",
            }
          : {})}
        onRetry={onRetry}
      />
    </SectionCard>
  );
}

export function OverviewPage() {
  const resource = useApiResource(loadOverview);
  const { healthState } = useOutletContext<{ healthState: ApiHealthState }>();

  if (resource.error) {
    return (
      <>
        <PageHeader
          title="Revenue Recovery"
          subtitle="Policy-governed recovery intelligence for failed payments."
        />
        <OverviewLoadFailure
          healthState={healthState}
          onRetry={resource.retry}
        />
      </>
    );
  }

  const summary = resource.data?.summary;
  const cases = resource.data?.cases ?? [];
  const evaluation = resource.data?.evaluation;
  const stories = detectDemoStories(cases);
  const recoveredProof = stories.find((story) => story.key === "realRecovery")?.caseItem ?? null;

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
        <div className="metrics-grid primary-metrics-grid">
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
            label="Requires Attention"
            value={String(summary.requires_attention)}
            caption="Review-required provider outcomes"
            icon={Users}
          />
        </div>
      )}

      {!resource.loading && summary ? (
        <div className="secondary-metrics-strip" aria-label="Secondary recovery metrics">
          <div>
            <CheckCircle2 size={17} aria-hidden="true" />
            <span><strong>{summary.recovered_cases}</strong> Recovered Cases</span>
            <small>{formatPercent(summary.recovery_rate_by_cases)} of evaluated cases</small>
          </div>
          <div>
            <Hourglass size={17} aria-hidden="true" />
            <span><strong>{summary.awaiting_outcome}</strong> Awaiting Outcome</span>
            <small>Provider outcome still pending</small>
          </div>
        </div>
      ) : null}

      <SectionCard
        className="control-loop-section"
        title="ARC recovery control loop"
        subtitle="Financial truth and authority remain deterministic around one bounded AI stage."
      >
        <div className="control-loop" aria-label="ARC recovery control loop">
          {controlSteps.map(({ label, note, icon: Icon, className }) => (
            <div className={`control-step ${className ?? ""}`} key={label}>
              <span className="control-step-icon">
                <Icon size={17} strokeWidth={1.8} aria-hidden="true" />
              </span>
              <strong>{label}</strong>
              <small>{note}</small>
            </div>
          ))}
        </div>
      </SectionCard>

      <SectionCard
        className="evidence-section"
        title="Evidence & Evaluation"
        subtitle="Provider proof and controlled evaluation remain deliberately separate."
      >
        {resource.loading || !evaluation ? (
          <div className="skeleton" style={{ minHeight: 260 }} />
        ) : (
          <EvidenceClasses evaluation={evaluation} recoveredProof={recoveredProof} />
        )}
      </SectionCard>

      <SectionCard
        className="demo-stories-section"
        title="Recovery Scenarios"
        subtitle="Four evidence stories demonstrate recovery, human authority, current-state protection, and deterministic stopping."
      >
        {resource.loading ? (
          <div className="demo-stories-grid" aria-label="Loading recovery scenarios">
            {Array.from({ length: 4 }, (_, index) => (
              <div className="skeleton demo-story-skeleton" key={index} />
            ))}
          </div>
        ) : (
          <DemoStories stories={stories} />
        )}
      </SectionCard>

      <SectionCard
        className="table-card"
        title="Cases Requiring Attention"
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

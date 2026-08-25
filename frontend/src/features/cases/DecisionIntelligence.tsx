import { AlertTriangle, Bot, CircleDollarSign, LockKeyhole, ShieldCheck } from "lucide-react";
import { OriginBadge, StatusBadge } from "../../components/Badges";
import { displayEnum } from "../../lib/display";
import { formatDateTime, formatMoney, formatPercent } from "../../lib/format";
import type { CaseDetail } from "../../types/api";

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function MissingCard({ title, message }: { title: string; message: string }) {
  return (
    <section className="intelligence-card">
      <div className="card-kicker"><h2>{title}</h2></div>
      <p className="muted">{message}</p>
    </section>
  );
}

export function DecisionIntelligence({ detail }: { detail: CaseDetail }) {
  const { diagnosis, strategy, policy, approval, execution, outcome, attribution } = detail;
  const strategyLabel = strategy?.provenance === "OPENAI"
    ? "OpenAI Strategy"
    : strategy?.provenance === "OFFLINE_SIMULATION"
      ? "Offline Strategy Simulation"
      : "Deterministic Strategy";

  return (
    <div className="intelligence-stack">
      <section className="intelligence-card">
        <div className="card-kicker">
          <h2>Diagnosis</h2>
          <span className="badge">Deterministic</span>
        </div>
        <dl className="detail-list">
          <Field label="Eligibility" value={displayEnum(diagnosis.eligibility_status)} />
          <Field label="Eligibility reason" value={displayEnum(diagnosis.eligibility_reason_code)} />
          <Field label="Failure category" value={displayEnum(diagnosis.failure_category)} />
          <Field label="Recovery disposition" value={displayEnum(diagnosis.recovery_disposition)} />
          <Field label="Diagnosis reason" value={displayEnum(diagnosis.diagnosis_reason_code)} />
          <Field label="Diagnosed" value={formatDateTime(diagnosis.diagnosed_at)} />
        </dl>
      </section>

      {strategy ? (
        <section className="intelligence-card">
          <div className="card-kicker">
            <h2>Strategy</h2>
            <span className="badge badge-info">
              {strategy.provenance === "DETERMINISTIC_RULE" ? <ShieldCheck size={12} aria-hidden="true" /> : <Bot size={12} aria-hidden="true" />}
              {strategyLabel}
            </span>
          </div>
          <dl className="detail-list">
            <Field label="Recommended action" value={displayEnum(strategy.action)} />
            <Field label="Reason" value={displayEnum(strategy.reason_code)} />
            {strategy.provenance === "OPENAI" ? (
              <>
                <Field label="Model" value={strategy.model ?? "Unavailable"} />
                <Field
                  label="Confidence"
                  value={strategy.confidence === null ? "Unavailable" : formatPercent(strategy.confidence)}
                />
              </>
            ) : null}
            <Field label="Proposed" value={formatDateTime(strategy.created_at)} />
          </dl>
          <p className="explanation">{strategy.explanation}</p>
          {strategy.provenance === "OPENAI" ? (
            <div className="authority-note">
              <LockKeyhole size={15} aria-hidden="true" />
              <span><strong>Model confidence does not authorize financial action.</strong> Deterministic policy retains authority.</span>
            </div>
          ) : strategy.provenance === "OFFLINE_SIMULATION" ? (
            <div className="authority-note offline-note">
              <ShieldCheck size={15} aria-hidden="true" />
              <span><strong>Controlled strategy fixture.</strong> Same bounded strategy schema. No external model call.</span>
            </div>
          ) : null}
        </section>
      ) : (
        <MissingCard
          title={detail.case.resolution_kind === "ALREADY_CAPTURED" ? "No intervention required" : "Strategy"}
          message={
            detail.case.resolution_kind === "ALREADY_CAPTURED"
              ? "Authoritative provider state showed the payment was already captured; ARC avoided an unnecessary recovery action."
              : "No recovery strategy was needed or recorded for this case."
          }
        />
      )}

      {policy ? (
        <section className="intelligence-card">
          <div className="card-kicker">
            <h2>Deterministic Policy</h2>
            <StatusBadge value={policy.result} />
          </div>
          <dl className="detail-list">
            <Field label="Policy result" value={displayEnum(policy.result)} />
            <Field label="Reason" value={displayEnum(policy.reason_code)} />
            <Field
              label="Approval threshold"
              value={formatMoney(policy.approval_threshold_minor, detail.case.currency)}
            />
            <Field label="Evaluated" value={formatDateTime(policy.evaluated_at)} />
          </dl>
          <p className="explanation">{policy.explanation}</p>
          <div className="authority-note">
            <ShieldCheck size={15} aria-hidden="true" />
            <span><strong>Strategy proposal ≠ financial authority.</strong> Merchant policy retains final authorization.</span>
          </div>
        </section>
      ) : (
        <MissingCard title="Deterministic Policy" message="No policy decision is recorded for this case." />
      )}

      {approval ? (
        <section className="intelligence-card">
          <div className="card-kicker">
            <h2>Human Approval</h2>
            <StatusBadge value={approval.approval_status} />
          </div>
          <dl className="detail-list">
            <Field label="Requested" value={formatDateTime(approval.requested_at)} />
            <Field label="Decided" value={formatDateTime(approval.decided_at)} />
          </dl>
          {approval.approval_status === "PENDING" ? (
            <div className="approval-attention">
              <strong>Operator action required.</strong> Approval controls are intentionally disabled in this read-only build.
            </div>
          ) : null}
        </section>
      ) : null}

      {execution ? (
        <section className="intelligence-card">
          <div className="card-kicker">
            <h2>Execution</h2>
            <StatusBadge value={execution.execution_status} />
          </div>
          <dl className="detail-list">
            <Field label="Action" value={displayEnum(execution.action)} />
            <Field label="Executor" value={displayEnum(execution.provider)} />
            <Field label="Latest provider status" value={displayEnum(execution.external_status)} />
            <Field label="Execution attempts" value={String(execution.execution_attempt_count)} />
            <Field label="Executed" value={formatDateTime(execution.executed_at)} />
            <Field label="Next evaluation" value={formatDateTime(execution.next_evaluation_at)} />
          </dl>
        </section>
      ) : null}

      {outcome ? (
        <section className="intelligence-card">
          <div className="card-kicker">
            <h2>Authoritative Outcome</h2>
            <StatusBadge value={outcome.outcome_status} />
          </div>
          <dl className="detail-list">
            <Field label="Provider status" value={displayEnum(outcome.provider_status)} />
            <Field label="Expected" value={formatMoney(outcome.amount_expected_minor, outcome.currency)} />
            <Field label="Amount paid" value={formatMoney(outcome.amount_paid_minor, outcome.currency)} />
            <Field label="Observed" value={formatDateTime(outcome.observed_at)} />
          </dl>
        </section>
      ) : null}

      {attribution ? (
        <section className="intelligence-card attribution-card">
          <div className="card-kicker">
            <h2>Revenue recovered</h2>
            <CircleDollarSign size={18} aria-hidden="true" />
          </div>
          <dl className="detail-list">
            <Field
              label="Attributed amount"
              value={formatMoney(attribution.recovered_amount_minor, attribution.currency)}
            />
            <Field label="Evidence" value="Evidence-backed attribution" />
            <Field label="Reason" value={displayEnum(attribution.reason_code)} />
            <Field label="Attributed" value={formatDateTime(attribution.attributed_at)} />
          </dl>
          <div style={{ marginTop: 14 }}><OriginBadge origin={detail.data_origin} /></div>
        </section>
      ) : detail.case.resolution_kind === "ARC_RECOVERED" && execution !== null ? (
        <div className="attention-banner">
          <AlertTriangle size={16} aria-hidden="true" />
          <div>
            <strong>Recovered without ARC attribution</strong>
            <p>Current payment truth is recovered, but no evidence-backed ARC attribution is recorded.</p>
          </div>
        </div>
      ) : null}
    </div>
  );
}

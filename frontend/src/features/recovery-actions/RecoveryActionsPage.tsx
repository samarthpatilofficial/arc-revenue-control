import { useCallback } from "react";
import { Link } from "react-router-dom";
import { OriginBadge, StatusBadge } from "../../components/Badges";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/Feedback";
import { PageHeader, SectionCard } from "../../components/Layout";
import { getRecoveryActions } from "../../lib/api";
import { displayEnum, shortReference, strategyProvenanceLabel } from "../../lib/display";
import { formatDateTime } from "../../lib/format";
import { useApiResource } from "../../lib/useApiResource";
import type { RecoveryActionItem } from "../../types/api";

export function RecoveryActionsTable({ actions }: { actions: RecoveryActionItem[] }) {
  return (
    <div className="table-shell">
      <table className="data-table">
        <caption className="sr-only">Governed recovery actions</caption>
        <thead>
          <tr>
            <th scope="col">Case</th>
            <th scope="col">Action</th>
            <th scope="col">Strategy source</th>
            <th scope="col">Executor</th>
            <th scope="col">Execution status</th>
            <th scope="col">Latest Provider Status</th>
            <th scope="col">Attempts</th>
            <th scope="col">Outcome</th>
            <th scope="col">Origin</th>
            <th scope="col">Executed</th>
            <th scope="col"><span className="sr-only">Trace</span></th>
          </tr>
        </thead>
        <tbody>
          {actions.map((item) => (
            <tr key={`${item.case_reference}-${item.action}`}>
              <td>
                <Link
                  className="table-link"
                  to={`/cases/${encodeURIComponent(item.case_reference)}`}
                  title={item.case_reference}
                >
                  {shortReference(item.case_reference)}
                </Link>
              </td>
              <td>{displayEnum(item.action)}</td>
              <td>
                {item.data_origin === "TEST_MODE" && item.strategy_provenance === "DETERMINISTIC_RULE"
                  ? "Deterministic Test Strategy"
                  : strategyProvenanceLabel(item.strategy_provenance)}
              </td>
              <td>{displayEnum(item.provider)}</td>
              <td><StatusBadge value={item.execution_status} /></td>
              <td>{displayEnum(item.external_status)}</td>
              <td className="money">{item.execution_attempt_count}</td>
              <td><StatusBadge value={item.outcome_status} /></td>
              <td><OriginBadge origin={item.data_origin} /></td>
              <td className="nowrap" title={item.executed_at ?? undefined}>
                {formatDateTime(item.executed_at)}
              </td>
              <td>
                <Link className="button button-secondary" to={`/cases/${encodeURIComponent(item.case_reference)}`}>
                  Open trace
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function RecoveryActionsPage() {
  const loader = useCallback((signal: AbortSignal) => getRecoveryActions(signal), []);
  const resource = useApiResource(loader);

  return (
    <>
      <PageHeader
        title="Recovery Actions"
        subtitle="Governed executions and their authoritative outcomes."
      />
      <SectionCard className="table-card">
        {resource.loading ? (
          <TableSkeleton rows={7} />
        ) : resource.error ? (
          <ErrorState onRetry={resource.retry} />
        ) : resource.data?.length ? (
          <RecoveryActionsTable actions={resource.data} />
        ) : (
          <EmptyState
            title="No recovery actions recorded"
            message="Governed action records will appear after policy-authorized execution."
          />
        )}
      </SectionCard>
    </>
  );
}

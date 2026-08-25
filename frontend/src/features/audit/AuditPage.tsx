import { useCallback } from "react";
import { ArrowUpRight, FileClock } from "lucide-react";
import { Link } from "react-router-dom";
import { OriginBadge, StatusBadge } from "../../components/Badges";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/Feedback";
import { PageHeader, SectionCard } from "../../components/Layout";
import { getCases } from "../../lib/api";
import { displayEnum, shortReference, strategyProvenanceLabel } from "../../lib/display";
import { formatMoney } from "../../lib/format";
import { useApiResource } from "../../lib/useApiResource";

export function AuditPage() {
  const loader = useCallback(
    (signal: AbortSignal) => getCases({ limit: 100 }, signal),
    [],
  );
  const resource = useApiResource(loader);

  return (
    <>
      <PageHeader
        title="Decision Audit"
        subtitle="Every governed recovery case has an inspectable decision trace."
        actions={<span className="badge"><FileClock size={13} aria-hidden="true" /> Append-oriented audit</span>}
      />
      <SectionCard
        className="table-card"
        title="Decision Trace Index"
        subtitle="Open a case to inspect chronological authority and provider evidence."
      >
        {resource.loading ? (
          <TableSkeleton rows={8} />
        ) : resource.error ? (
          <ErrorState onRetry={resource.retry} />
        ) : resource.data?.length ? (
          <div className="table-shell">
            <table className="data-table">
              <caption className="sr-only">Decision trace index</caption>
              <thead>
                <tr>
                  <th scope="col">Case</th>
                  <th scope="col">Amount</th>
                  <th scope="col">Diagnosis</th>
                  <th scope="col">Strategy</th>
                  <th scope="col">Policy</th>
                  <th scope="col">Final state</th>
                  <th scope="col">Origin</th>
                  <th scope="col"><span className="sr-only">Action</span></th>
                </tr>
              </thead>
              <tbody>
                {resource.data.map((item) => (
                  <tr key={item.case_reference}>
                    <td>
                      <Link
                        className="table-link"
                        to={`/cases/${encodeURIComponent(item.case_reference)}`}
                        title={item.case_reference}
                      >
                        {shortReference(item.case_reference)}
                      </Link>
                    </td>
                    <td className="money">{formatMoney(item.amount_minor, item.currency)}</td>
                    <td>{displayEnum(item.failure_category)}</td>
                    <td>
                      <span className="table-primary">
                        {item.strategy_action ? displayEnum(item.strategy_action) : "Bypassed — not required"}
                      </span>
                      <span className="table-secondary">
                        {strategyProvenanceLabel(item.strategy_provenance)}
                      </span>
                    </td>
                    <td><StatusBadge value={item.policy_result} /></td>
                    <td><StatusBadge value={item.resolution_kind} /></td>
                    <td><OriginBadge origin={item.data_origin} /></td>
                    <td>
                      <Link className="button button-secondary" to={`/cases/${encodeURIComponent(item.case_reference)}`}>
                        Open Trace <ArrowUpRight size={13} aria-hidden="true" />
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <EmptyState
            title="No decision traces available"
            message="Reconciled cases will appear here with their persisted audit history."
          />
        )}
      </SectionCard>
    </>
  );
}

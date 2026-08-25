import { useCallback } from "react";
import { ArrowUpRight, ShieldAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { OriginBadge, StatusBadge } from "../../components/Badges";
import { EmptyState, ErrorState, TableSkeleton } from "../../components/Feedback";
import { PageHeader, SectionCard } from "../../components/Layout";
import { getApprovals } from "../../lib/api";
import { displayEnum, shortReference, strategyProvenanceLabel } from "../../lib/display";
import { formatDateTime, formatMoney } from "../../lib/format";
import { useApiResource } from "../../lib/useApiResource";
import type { ApprovalQueueItem } from "../../types/api";

export function ApprovalQueue({ approvals }: { approvals: ApprovalQueueItem[] }) {
  return (
    <div className="table-shell">
      <table className="data-table">
        <caption className="sr-only">Pending human approval queue</caption>
        <thead>
          <tr>
            <th scope="col">Case</th>
            <th scope="col">Amount</th>
            <th scope="col">Proposed action</th>
            <th scope="col">Strategy source</th>
            <th scope="col">Policy reason</th>
            <th scope="col">Requested</th>
            <th scope="col">Origin</th>
            <th scope="col">Status</th>
            <th scope="col"><span className="sr-only">Action</span></th>
          </tr>
        </thead>
        <tbody>
          {approvals.map((item) => (
            <tr key={item.approval_request_id}>
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
              <td>{displayEnum(item.strategy_action)}</td>
              <td>{strategyProvenanceLabel(item.strategy_provenance)}</td>
              <td>{displayEnum(item.policy_reason_code)}</td>
              <td className="nowrap" title={item.requested_at}>{formatDateTime(item.requested_at)}</td>
              <td><OriginBadge origin={item.data_origin} /></td>
              <td><StatusBadge value={item.approval_status} /></td>
              <td>
                <Link className="button button-secondary" to={`/cases/${encodeURIComponent(item.case_reference)}`}>
                  Review Case <ArrowUpRight size={13} aria-hidden="true" />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ApprovalsPage() {
  const loader = useCallback((signal: AbortSignal) => getApprovals(signal), []);
  const resource = useApiResource(loader);

  return (
    <>
      <PageHeader
        title="Approvals"
        subtitle="Recovery decisions requiring human authority."
      />
      <div className="attention-banner">
        <ShieldAlert size={17} aria-hidden="true" />
        <div>
          <strong>Human authority is preserved</strong>
          <p>Strategy proposes. Policy escalates. Human authority is preserved. Operators review the complete case trace before any approval decision.</p>
        </div>
      </div>
      <SectionCard className="table-card">
        {resource.loading ? (
          <TableSkeleton rows={5} />
        ) : resource.error ? (
          <ErrorState onRetry={resource.retry} />
        ) : resource.data?.length ? (
          <ApprovalQueue approvals={resource.data} />
        ) : (
          <EmptyState
            title="No approvals require attention"
            message="Pending high-value or policy-sensitive decisions will appear here."
          />
        )}
      </SectionCard>
    </>
  );
}

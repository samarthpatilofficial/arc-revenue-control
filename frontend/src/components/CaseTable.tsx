import { Link } from "react-router-dom";
import { caseContextLabel } from "../lib/caseContext";
import { displayEnum, shortReference, strategyProvenanceLabel } from "../lib/display";
import { formatMoney } from "../lib/format";
import type { CaseListItem } from "../types/api";
import { OriginBadge, StatusBadge } from "./Badges";

export function CaseTable({
  cases,
  compact = false,
}: {
  cases: CaseListItem[];
  compact?: boolean;
}) {
  return (
    <div className="table-shell">
      <table className={`data-table case-table ${compact ? "compact" : ""}`.trim()}>
        <caption className="sr-only">Revenue recovery cases</caption>
        <thead>
          <tr>
            <th scope="col">Case</th>
            <th scope="col">Amount</th>
            <th scope="col">Diagnosis</th>
            <th scope="col">Strategy</th>
            <th scope="col">Policy</th>
            <th scope="col">State</th>
            <th scope="col">Origin</th>
            <th scope="col"><span className="sr-only">Open case</span></th>
          </tr>
        </thead>
        <tbody>
          {cases.map((item) => (
            <tr key={item.case_reference}>
              <td>
                <Link
                  className="table-link case-context-link"
                  to={`/cases/${encodeURIComponent(item.case_reference)}`}
                  title={item.case_reference}
                >
                  <span className="table-primary">{caseContextLabel(item)}</span>
                  <code className="case-reference">{shortReference(item.case_reference)}</code>
                </Link>
              </td>
              <td className="money">
                {formatMoney(item.amount_minor, item.currency)}
              </td>
              <td>
                <span className="table-primary">
                  {displayEnum(item.failure_category)}
                </span>
                {item.recovery_disposition ? (
                  <span className="table-secondary">
                    {displayEnum(item.recovery_disposition)}
                  </span>
                ) : null}
              </td>
              <td>
                <span className="table-primary">
                  {item.strategy_action
                    ? displayEnum(item.strategy_action)
                    : "Bypassed — not required"}
                </span>
                <span className="table-secondary">
                  {strategyProvenanceLabel(item.strategy_provenance)}
                </span>
              </td>
              <td><StatusBadge value={item.policy_result} /></td>
              <td><StatusBadge value={item.resolution_kind} /></td>
              <td><OriginBadge origin={item.data_origin} /></td>
              <td>
                <Link
                  className="button button-secondary table-action"
                  to={`/cases/${encodeURIComponent(item.case_reference)}`}
                >
                  View
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

import { Link } from "react-router-dom";
import { displayEnum, shortReference } from "../lib/display";
import { formatDateTime, formatMoney } from "../lib/format";
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
      <table className="data-table">
        <caption className="sr-only">Revenue recovery cases</caption>
        <thead>
          <tr>
            <th scope="col">Case</th>
            <th scope="col">Amount</th>
            {!compact ? <th scope="col">Payment method</th> : null}
            <th scope="col">Diagnosis</th>
            <th scope="col">Strategy</th>
            <th scope="col">Policy</th>
            <th scope="col">Status</th>
            <th scope="col">Origin</th>
            <th scope="col">Detected</th>
          </tr>
        </thead>
        <tbody>
          {cases.map((item) => (
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
              <td className="money">
                {formatMoney(item.amount_minor, item.currency)}
              </td>
              {!compact ? (
                <td>{displayEnum(item.payment_method)}</td>
              ) : null}
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
              <td>{displayEnum(item.strategy_action)}</td>
              <td><StatusBadge value={item.policy_result} /></td>
              <td><StatusBadge value={item.current_state} /></td>
              <td><OriginBadge origin={item.data_origin} /></td>
              <td className="nowrap" title={item.detected_at}>
                {formatDateTime(item.detected_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

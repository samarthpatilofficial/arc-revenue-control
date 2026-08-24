import { AlertTriangle, Inbox, RotateCw } from "lucide-react";
import { Link } from "react-router-dom";

export function ErrorState({
  title = "Unable to load recovery data",
  message = "The read API did not return a usable response.",
  onRetry,
}: {
  title?: string;
  message?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="error-state" role="alert">
      <div>
        <div className="error-state-icon">
          <AlertTriangle size={20} aria-hidden="true" />
        </div>
        <h2>{title}</h2>
        <p>{message}</p>
        {onRetry ? (
          <button className="button" type="button" onClick={onRetry}>
            <RotateCw size={14} aria-hidden="true" /> Retry
          </button>
        ) : (
          <Link className="button" to="/cases">
            Back to cases
          </Link>
        )}
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  message,
}: {
  title: string;
  message: string;
}) {
  return (
    <div className="empty-state">
      <div>
        <div className="empty-state-icon">
          <Inbox size={20} aria-hidden="true" />
        </div>
        <h3>{title}</h3>
        <p>{message}</p>
      </div>
    </div>
  );
}

export function MetricSkeletons() {
  return (
    <div className="metrics-grid" aria-label="Loading recovery metrics">
      {Array.from({ length: 6 }, (_, index) => (
        <div className="skeleton skeleton-metric" key={index} />
      ))}
    </div>
  );
}

export function TableSkeleton({ rows = 6 }: { rows?: number }) {
  return (
    <div aria-label="Loading table">
      {Array.from({ length: rows }, (_, index) => (
        <div className="skeleton skeleton-table-row" key={index} />
      ))}
    </div>
  );
}

export function DetailSkeleton() {
  return (
    <div className="detail-grid" aria-label="Loading case detail">
      <div className="intelligence-stack">
        {Array.from({ length: 4 }, (_, index) => (
          <div className="skeleton" style={{ height: 150 }} key={index} />
        ))}
      </div>
      <div className="skeleton" style={{ height: 560 }} />
    </div>
  );
}

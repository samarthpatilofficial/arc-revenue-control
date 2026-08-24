import type { LucideIcon } from "lucide-react";

export function MetricCard({
  label,
  value,
  caption,
  icon: Icon,
}: {
  label: string;
  value: string;
  caption: string;
  icon: LucideIcon;
}) {
  return (
    <article className="metric-card">
      <div className="metric-label">
        <span>{label}</span>
        <Icon className="metric-icon" size={16} strokeWidth={1.8} aria-hidden="true" />
      </div>
      <div className="metric-value">{value}</div>
      <div className="metric-caption">{caption}</div>
    </article>
  );
}

import {
  Bot,
  Check,
  CircleDollarSign,
  ClipboardCheck,
  Eye,
  Gauge,
  SearchCheck,
  ShieldCheck,
  Sparkles,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import {
  authorityLabel,
  displayEnum,
  displayTimelineDetail,
  displayTimelineTitle,
  strategyProvenanceLabel,
} from "../lib/display";
import { formatDateTime, formatMoney } from "../lib/format";
import type { TimelineItem } from "../types/api";
import { AuthorityBadge, OriginBadge, StatusBadge } from "./Badges";

const stageIcons: Readonly<Record<string, LucideIcon>> = {
  DEMO: Sparkles,
  DETECTED: Gauge,
  RECONCILED: SearchCheck,
  ELIGIBILITY: Check,
  DIAGNOSED: Wrench,
  STRATEGY: Bot,
  POLICY: ShieldCheck,
  APPROVAL: ClipboardCheck,
  EXECUTION: Gauge,
  OUTCOME: Eye,
  ATTRIBUTION: CircleDollarSign,
};

export function DecisionTimeline({ items }: { items: TimelineItem[] }) {
  return (
    <ol className="timeline" aria-label="Case decision trace">
      {items.map((item, index) => {
        const Icon = stageIcons[item.stage] ?? Gauge;
        const detail = item.amount_minor !== null && item.currency
          ? formatMoney(item.amount_minor, item.currency)
          : displayTimelineDetail(item);
        return (
          <li
            className={`timeline-item ${item.status}`}
            key={`${item.timestamp}-${item.stage}-${index}`}
          >
            <span className="timeline-marker">
              <Icon size={13} strokeWidth={2} aria-hidden="true" />
            </span>
            <p className="timeline-title">{displayTimelineTitle(item)}</p>
            <p className="timeline-time" title={item.timestamp}>
              {formatDateTime(item.timestamp)}
            </p>
            {detail ? <p className="timeline-detail">{detail}</p> : null}
            <div className="timeline-tags">
              <AuthorityBadge authority={item.authority} />
              {item.result ? <StatusBadge value={item.result} /> : null}
              {item.action ? <span className="badge">{displayEnum(item.action)}</span> : null}
              {item.strategy_provenance ? (
                <span className="badge">{strategyProvenanceLabel(item.strategy_provenance)}</span>
              ) : null}
              {item.data_origin ? <OriginBadge origin={item.data_origin} /> : null}
            </div>
            <span className="sr-only">Authority: {authorityLabel(item.authority)}</span>
          </li>
        );
      })}
    </ol>
  );
}

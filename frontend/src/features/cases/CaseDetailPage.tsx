import { useCallback } from "react";
import { ArrowLeft } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { DecisionTimeline } from "../../components/DecisionTimeline";
import { DetailSkeleton, ErrorState } from "../../components/Feedback";
import { PageHeader, SectionCard } from "../../components/Layout";
import { OriginBadge, StatusBadge } from "../../components/Badges";
import { ApiError, getCaseDetail, getCaseTimeline } from "../../lib/api";
import { detailTitle } from "../../lib/casePresentation";
import { shortReference } from "../../lib/display";
import { formatDateTime, formatMoney } from "../../lib/format";
import { useApiResource } from "../../lib/useApiResource";
import type { CaseDetail, TimelineItem } from "../../types/api";
import { CaseStoryBanner } from "./CaseStoryBanner";
import { DecisionIntelligence } from "./DecisionIntelligence";

interface CasePageData {
  detail: CaseDetail;
  timeline: TimelineItem[];
}

export function CaseDetailPage() {
  const { caseReference } = useParams();
  const loadDetail = useCallback(
    (signal: AbortSignal): Promise<CasePageData> => {
      if (!caseReference) {
        return Promise.reject(new ApiError("Case not found", 404, "CASE_NOT_FOUND"));
      }
      return Promise.all([
        getCaseDetail(caseReference, signal),
        getCaseTimeline(caseReference, signal),
      ]).then(([detail, timeline]) => ({ detail, timeline }));
    },
    [caseReference],
  );
  const resource = useApiResource(loadDetail);

  if (resource.error) {
    const notFound = resource.error instanceof ApiError && resource.error.status === 404;
    return (
      <SectionCard className="not-found">
        <ErrorState
          title={notFound ? "Case not found" : "Unable to load case detail"}
          message={
            notFound
              ? "The requested case is not available in the read model."
              : "ARC could not load the case and its decision trace."
          }
          {...(!notFound ? { onRetry: resource.retry } : {})}
        />
      </SectionCard>
    );
  }

  const detail = resource.data?.detail;
  const timeline = resource.data?.timeline ?? [];
  return (
    <>
      <PageHeader
        title={detail ? detailTitle(detail) : "Case Decision Trace"}
        subtitle={detail ? "Complete decision, authority, execution, and evidence record." : "End-to-end authority, execution, provider evidence, and attribution."}
        actions={
          <Link className="button button-secondary" to="/cases">
            <ArrowLeft size={14} aria-hidden="true" /> Back to cases
          </Link>
        }
      />

      {resource.loading || !detail ? (
        <DetailSkeleton />
      ) : (
        <>
          <div className="detail-header">
            <div className="detail-title-block">
              <span className="detail-eyebrow">Case amount</span>
              <div className="detail-amount">
                {formatMoney(detail.case.amount_minor, detail.case.currency)}
              </div>
              <div className="detail-meta">
                <code title={detail.case.case_reference}>{shortReference(detail.case.case_reference)}</code>
                <span title={detail.case.detected_at}>Detected {formatDateTime(detail.case.detected_at)}</span>
              </div>
            </div>
            <div className="detail-statuses">
              <StatusBadge value={detail.case.resolution_kind} />
              <OriginBadge origin={detail.data_origin} />
            </div>
          </div>
          <CaseStoryBanner detail={detail} />
          <div className="detail-grid">
            <DecisionIntelligence detail={detail} />
            <SectionCard
              className="timeline-panel"
              title="Decision trace"
              subtitle="Chronological persisted authority and outcome record."
            >
              <DecisionTimeline items={timeline} />
            </SectionCard>
          </div>
        </>
      )}
    </>
  );
}

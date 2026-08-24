import { AuthorityBadge, OriginBadge } from "../../components/Badges";
import type { CaseDetail } from "../../types/api";
import { caseStoryBanner } from "./storyBannerRules";

export function CaseStoryBanner({ detail }: { detail: CaseDetail }) {
  const banner = caseStoryBanner(detail);
  if (!banner) return null;
  const Icon = banner.icon;
  return (
    <aside className={`case-story-banner ${banner.tone}`} aria-label={banner.title}>
      <span className="case-story-banner-icon">
        <Icon size={18} strokeWidth={1.9} aria-hidden="true" />
      </span>
      <div className="case-story-banner-copy">
        <strong>{banner.title}</strong>
        <p>{banner.message}</p>
      </div>
      <div className="case-story-banner-tags">
        <AuthorityBadge authority={banner.authority} />
        <OriginBadge origin={detail.data_origin} />
      </div>
    </aside>
  );
}

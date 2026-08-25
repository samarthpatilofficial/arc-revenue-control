import {
  ArrowUpRight,
  AlertTriangle,
  CheckCircle2,
  SearchCheck,
  ShieldCheck,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { Link } from "react-router-dom";
import { AuthorityBadge, OriginBadge, StatusBadge } from "../../components/Badges";
import { formatMoney } from "../../lib/format";
import type { DemoStory, DemoStoryKey } from "./storyDetection";

const STORY_ICONS: Readonly<Record<DemoStoryKey, LucideIcon>> = {
  realRecovery: CheckCircle2,
  highValueApproval: ShieldCheck,
  alreadyCaptured: SearchCheck,
  hardStop: AlertTriangle,
};

export function DemoStories({ stories }: { stories: DemoStory[] }) {
  return (
    <div className="demo-stories-grid">
      {stories.map((story) => {
        const Icon = STORY_ICONS[story.key];
        if (!story.caseItem) {
          return (
            <article className="demo-story-card unavailable" key={story.key}>
              <div className="demo-story-heading">
                <span className="demo-story-icon"><Icon size={16} aria-hidden="true" /></span>
                <h3>{story.title}</h3>
              </div>
              <p>{story.explanation}</p>
              <div className="demo-story-unavailable">
                <strong>Demo scenario unavailable</strong>
                <span>Run the deterministic demo preflight.</span>
              </div>
            </article>
          );
        }
        return (
          <article className={`demo-story-card ${story.key}`} key={story.key}>
            <div className="demo-story-heading">
              <span className="demo-story-icon"><Icon size={16} aria-hidden="true" /></span>
              <h3>{story.title}</h3>
            </div>
            <p>{story.explanation}</p>
            <div className="demo-story-amount">
              {story.key === "alreadyCaptured"
                ? "No recovery attributed"
                : formatMoney(story.amountMinor, story.currency)}
            </div>
            <div className="demo-story-meta">
              <StatusBadge value={story.caseItem.resolution_kind} />
              <OriginBadge origin={story.caseItem.data_origin} />
            </div>
            <div className="demo-story-authority">
              <AuthorityBadge authority={story.authority} />
            </div>
            <Link
              className="demo-story-link"
              to={`/cases/${encodeURIComponent(story.caseItem.case_reference)}`}
            >
              Open case <ArrowUpRight size={13} aria-hidden="true" />
            </Link>
          </article>
        );
      })}
    </div>
  );
}

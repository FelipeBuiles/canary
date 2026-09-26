import { FeedbackButton } from "../components/FeedbackButton";
import { Link, useParams } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { STAGE_ORDER } from "../types/api";
import { getBackendStageUiLabel, getUiCompletedCount, UI_STAGES } from "../lib/uiStages";
import { getCachedBranding } from "../lib/legal";
import { SupportLink } from "../components/SupportLink";

export function Footer() {
  const { id } = useParams();
  const { data: status } = useProjectStatus(id);
  const branding = getCachedBranding();

  const completedStages = status
    ? getUiCompletedCount(status)
    : 0;
  const activeStage =
    status &&
    (STAGE_ORDER.find((stage) => {
      const stageStatus = status.stages[stage]?.status;
      return stageStatus === "running" || stageStatus === "awaiting_review";
    }) ?? null);

  return (
    <footer className="shrink-0 border-t-[2px] border-hero-red bg-ink-black text-bristol">
      <div className="flex min-h-[34px] items-center justify-between gap-4 px-4 lg:px-5">
        <span className="font-meta text-[0.55rem] tracking-[0.2em] text-narrator-gold">
          {branding.product_name.toUpperCase()} © 2026
        </span>

        <div className="flex flex-wrap items-center gap-4 text-[0.55rem] sm:gap-5">
          <span className="font-meta tracking-[0.12em] text-bristol/80 tabular-nums">
            Progress: {completedStages}/{UI_STAGES.length}
          </span>
          <span className="font-meta tracking-[0.12em] text-narrator-gold">
            Status: {activeStage ? getBackendStageUiLabel(activeStage).toUpperCase() : "Standby"}
          </span>
        </div>
      </div>

      {/* Legal links row — present on every page. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-bristol/12 px-4 py-1.5 lg:px-5">
        <Link
          to="/legal/terms"
          className="font-meta text-[0.5rem] tracking-[0.14em] text-bristol/55 transition-colors hover:text-bristol"
        >
          TERMS
        </Link>
        <Link
          to="/legal/privacy"
          className="font-meta text-[0.5rem] tracking-[0.14em] text-bristol/55 transition-colors hover:text-bristol"
        >
          PRIVACY
        </Link>
        <Link
          to="/legal/acceptable-use"
          className="font-meta text-[0.5rem] tracking-[0.14em] text-bristol/55 transition-colors hover:text-bristol"
        >
          ACCEPTABLE USE
        </Link>
        <a
          href={`mailto:${branding.legal_email}`}
          className="font-meta text-[0.5rem] tracking-[0.14em] text-bristol/55 transition-colors hover:text-bristol"
        >
          REPORT ABUSE
        </a>
        <FeedbackButton projectId={id} />
        <SupportLink
          diagnostics={{
            releaseSha: import.meta.env.VITE_CANARY_VERSION,
            projectId: id,
            stationOrStage: activeStage,
            errorCategory: "pipeline_help",
          }}
          className="font-meta text-[0.5rem] tracking-[0.14em] text-narrator-gold transition-colors hover:text-bristol"
        >
          NEED HELP?
        </SupportLink>
      </div>
    </footer>
  );
}

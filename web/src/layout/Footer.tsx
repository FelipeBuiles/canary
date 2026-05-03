import { useParams } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { STAGE_ORDER } from "../types/api";
import { getBackendStageUiLabel, getUiCompletedCount, UI_STAGES } from "../lib/uiStages";

export function Footer() {
  const { name } = useParams();
  const { data: status } = useProjectStatus(name);

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
          NARRATIVE FRAME STUDIO © 2026
        </span>

        <div className="flex flex-wrap items-center gap-5 text-[0.55rem]">
          <span className="font-meta tracking-[0.12em] text-bristol/80 tabular-nums">
            Progress: {completedStages}/{UI_STAGES.length}
          </span>
          <span className="font-meta tracking-[0.12em] text-narrator-gold">
            Status: {activeStage ? getBackendStageUiLabel(activeStage).toUpperCase() : "Standby"}
          </span>
        </div>
      </div>
    </footer>
  );
}

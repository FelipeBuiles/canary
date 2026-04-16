import { useParams } from "react-router-dom";
import { useProjectStatus } from "../api/queries";
import { STAGE_DISPLAY_NAMES, STAGE_ORDER } from "../types/api";

export function Footer() {
  const { name } = useParams();
  const { data: status } = useProjectStatus(name);

  const completedStages = status
    ? STAGE_ORDER.filter((stage) => status.stages[stage]?.status === "complete").length
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
          <span className="font-meta tracking-[0.12em] text-bristol/80">
            Usage: ${(status?.total_cost_usd ?? 0).toFixed(2)}
          </span>
          <span className="font-meta tracking-[0.12em] text-bristol/80">
            Progress: {completedStages}/7
          </span>
          <span className="font-meta tracking-[0.12em] text-narrator-gold">
            Status: {activeStage ? STAGE_DISPLAY_NAMES[activeStage] : "Standby"}
          </span>
        </div>
      </div>
    </footer>
  );
}

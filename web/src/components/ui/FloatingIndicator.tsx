import { useParams, useNavigate } from "react-router-dom";
import { useProjectStatus } from "../../api/queries";
import { STAGE_DISPLAY_NAMES, STAGE_ORDER, STAGE_ROUTES } from "../../types/api";
import { Icon } from "./Icon";
import { cn } from "../../lib/cn";

export function FloatingIndicator() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const { data: status } = useProjectStatus(name);

  if (!name || !status || !status.is_running) {
    return null;
  }

  const runningStage = STAGE_ORDER.find(
    (stage) => status.stages[stage]?.status === "running"
  );

  if (!runningStage) {
    return null;
  }

  const stageInfo = status.stages[runningStage];
  const route = STAGE_ROUTES[runningStage];
  const jumpPath = `/project/${encodeURIComponent(name)}/${route}`;

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "fixed bottom-[50px] right-5 z-40 flex flex-col gap-2 rounded-full border-[2px] border-ink-black bg-bristol p-4 shadow-ink-md",
      )}
    >
      <div className="flex items-center gap-3">
        <div className="flex h-8 w-8 items-center justify-center">
          <Icon name="loader" size={20} className="animate-spin text-narrator-gold" />
        </div>
        <div>
          <div className="font-meta text-[0.6rem] tracking-[0.18em] text-narrator-gold animate-pulse">
            RUNNING
          </div>
          <div className="font-display text-[0.9rem] font-bold tracking-[-0.03em]">
            {STAGE_DISPLAY_NAMES[runningStage]}
          </div>
        </div>
      </div>

      {stageInfo.items_total > 0 && (
        <div className="space-y-1">
          <div className="flex items-center justify-between font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/55">
            <span>{stageInfo.items_done} / {stageInfo.items_total}</span>
            <span>{Math.round((stageInfo.items_done / stageInfo.items_total) * 100)}%</span>
          </div>
          <div className="h-2 w-full overflow-hidden rounded-full border border-ink-black bg-pulp-paper">
            <div
              className="h-full bg-narrator-gold transition-all duration-300"
              style={{ width: `${(stageInfo.items_done / stageInfo.items_total) * 100}%` }}
            />
          </div>
        </div>
      )}

      <button
        onClick={() => navigate(jumpPath)}
        className="flex items-center justify-center gap-1 rounded border-[2px] border-ink-black bg-pulp-paper px-3 py-1.5 font-meta text-[0.55rem] tracking-[0.16em] hover:bg-ink-black/5 transition-colors"
      >
        JUMP TO {STAGE_DISPLAY_NAMES[runningStage].toUpperCase()}
        <Icon name="arrow-right" size={10} />
      </button>
    </div>
  );
}

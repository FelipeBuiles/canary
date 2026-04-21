import { useParams, useNavigate, useLocation } from "react-router-dom";
import { useProjectStatus } from "../../api/queries";
import { STAGE_DISPLAY_NAMES, STAGE_ORDER, STAGE_ROUTES } from "../../types/api";
import { Icon } from "./Icon";
import { cn } from "../../lib/cn";

export function FloatingIndicator() {
  const { name } = useParams<{ name: string }>();
  const navigate = useNavigate();
  const location = useLocation();
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
  const onRunningStageScreen = location.pathname === jumpPath;

  if (onRunningStageScreen) {
    return null;
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "fixed bottom-4 right-4 z-40 w-[280px] border-[2px] border-ink-black bg-bristol shadow-ink-md",
      )}
    >
      <div className="flex items-center gap-3 border-b-[2px] border-ink-black bg-pulp-paper px-3 py-2">
        <div className="flex h-7 w-7 items-center justify-center border border-ink-black bg-bristol">
          <Icon name="loader" size={14} className="animate-spin text-narrator-gold" />
        </div>
        <div>
          <div className="font-meta text-[0.5rem] tracking-[0.18em] text-ink-black animate-pulse">
            RUNNING
          </div>
          <div className="font-display text-[0.82rem] font-bold tracking-[-0.03em]">
            {STAGE_DISPLAY_NAMES[runningStage]}
          </div>
        </div>
      </div>

      <div className="space-y-2 p-3">
        {stageInfo.items_total > 0 && (
          <>
            <div className="flex items-center justify-between font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/55">
              <span>{stageInfo.items_done} / {stageInfo.items_total}</span>
              <span>{Math.round((stageInfo.items_done / stageInfo.items_total) * 100)}%</span>
            </div>
            <div className="h-2 w-full overflow-hidden border border-ink-black bg-pulp-paper">
              <div
                className="h-full bg-narrator-gold transition-all duration-300"
                style={{ width: `${(stageInfo.items_done / stageInfo.items_total) * 100}%` }}
              />
            </div>
          </>
        )}

        <button
          onClick={() => navigate(jumpPath)}
          className="flex w-full items-center justify-center gap-1 border-[2px] border-ink-black bg-pulp-paper px-3 py-1.5 font-meta text-[0.55rem] tracking-[0.16em] hover:bg-ink-black/5 transition-colors"
        >
          JUMP TO {STAGE_DISPLAY_NAMES[runningStage].toUpperCase()}
          <Icon name="arrow-right" size={10} />
        </button>
      </div>
    </div>
  );
}

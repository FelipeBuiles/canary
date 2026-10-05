import { skipToken, useQuery } from "@tanstack/react-query";
import { useParams, useNavigate, useLocation } from "react-router-dom";
import { useProjectStatus } from "../../api/queries";
import { STAGE_ORDER } from "../../types/api";
import { getBackendStageUiLabel } from "../../lib/uiStages";
import { BACKEND_STAGE_TO_STATION_ROUTE } from "../../lib/stations";
import {
  activityQueryKey,
  barSegments,
  isStalled,
  type StageActivityMap,
} from "../../lib/stageActivity";
import { useNow } from "../../hooks/useNow";
import { Icon } from "./Icon";
import { styleBatchSummary } from "../style/styleBatch";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";

export function FloatingIndicator() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const { data: status } = useProjectStatus(id);
  // SSE-fed only; this observer has no network query.
  const { data: activityMap } = useQuery<StageActivityMap>({
    queryKey: activityQueryKey(id ?? ""),
    queryFn: skipToken,
    initialData: {},
  });
  // Ticks so a stream that goes quiet ages into "still waiting" on its own.
  const now = useNow(5_000, Boolean(status?.is_running));

  if (!id || !status || !status.is_running) {
    return null;
  }

  const activeJob = status.active_jobs?.find((job) => job.status === "running")
    ?? status.active_jobs?.find((job) => job.status === "queued");
  const runningStage = activeJob?.stage && STAGE_ORDER.includes(activeJob.stage)
    ? activeJob.stage : undefined;

  if (!runningStage) {
    return null;
  }

  const stageInfo = status.stages[runningStage];
  // A Style batch chooses directions and designs lettering before any proof
  // exists, so it reports its step, and counts proofs only while painting them.
  const styleBatch = runningStage === "style" ? styleBatchSummary(activeJob) : null;
  const itemsDone = styleBatch ? styleBatch.proofs?.done ?? 0 : stageInfo.items_done;
  const itemsTotal = styleBatch ? styleBatch.proofs?.total ?? 0 : stageInfo.items_total;
  const activity = activityMap?.[runningStage];
  const stalled = activity ? isStalled(activity, now) : false;
  const { donePct, inFlightPct } = barSegments(
    itemsDone,
    itemsTotal,
    styleBatch ? undefined : activity,
    now,
  );
  const route = BACKEND_STAGE_TO_STATION_ROUTE[runningStage];
  const stageLabel = getBackendStageUiLabel(runningStage).toUpperCase();
  const jumpPath = `/project/${encodeURIComponent(id)}/${route}`;
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
          <span aria-hidden="true" className="h-2.5 w-2.5 bg-hero-red" />
        </div>
        <div>
          <div className="font-meta text-xs font-bold tracking-[0.08em] text-ink-muted">
            {activeJob?.status === "queued" ? "QUEUED" : "RUNNING"}
          </div>
          <div className="font-display text-[0.82rem] font-bold tracking-[-0.03em]">
            {stageLabel}
          </div>
        </div>
      </div>

      <div className="space-y-2 p-3">
        {styleBatch && (
          <div className="font-meta text-xs text-ink-muted">
            {t("Step {step} of {steps}", { step: styleBatch.step, steps: styleBatch.steps })} · {t(styleBatch.label)}
          </div>
        )}
        {itemsTotal > 0 && (
          <>
            <div className="flex items-center justify-between font-meta text-xs tabular-nums text-ink-muted">
              <span>{styleBatch ? `${itemsDone} / ${itemsTotal} ${t("proofs")}` : `${itemsDone} / ${itemsTotal}`}</span>
              <span>{Math.round(donePct)}%</span>
            </div>
            <div className="relative h-2 w-full overflow-hidden border border-ink-black bg-pulp-paper">
              <div
                className="absolute inset-0 origin-left bg-narrator-gold transition-transform duration-[var(--motion-settle)]"
                style={{ transform: `scaleX(${donePct / 100})` }}
              />
              {inFlightPct > 0 && (
                <div
                  data-testid="in-flight-bar"
                  className="absolute inset-0 origin-left bg-narrator-gold/40 transition-transform duration-[var(--motion-settle)]"
                  style={{ transform: `translateX(${donePct}%) scaleX(${inFlightPct / 100})` }}
                />
              )}
            </div>
          </>
        )}

        {activity?.detail && (
          <div className="font-meta text-xs leading-5 text-ink-muted">
            {stalled ? `${activity.detail} — still waiting` : activity.detail}
          </div>
        )}

        <button
          onClick={() => navigate(jumpPath)}
          className="flex min-h-11 w-full items-center justify-center gap-1 border-[2px] border-ink-black bg-pulp-paper px-3 py-1.5 font-meta text-xs tracking-[0.08em] hover:bg-ink-black/5 transition-colors"
        >
          JUMP TO {stageLabel}
          <Icon name="arrow-right" size={10} />
        </button>
      </div>
    </div>
  );
}

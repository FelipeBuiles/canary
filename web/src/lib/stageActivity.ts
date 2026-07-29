/**
 * Sub-item stage activity — the in-flight detail a `stage_progress` count can't
 * carry.
 *
 * Text stages stream, so the backend reports how much of the current item has
 * arrived (`fraction`) plus a heartbeat (`at`). That signal is advisory: it can
 * move backwards when a request retries, so it lives in its own cache entry
 * rather than in `ProjectStatus.items_done`, which the status poll reconciles
 * and must never regress.
 */
import type { QueryClient } from "@tanstack/react-query";
import type { PipelineEvent } from "../types/api";

export interface StageActivity {
  /** 0..1 through the item being worked on, or null when unpredictable. */
  fraction: number | null;
  /** Human label for the sub-step, e.g. "repairing 2 of 4 shards". */
  detail: string | null;
  /** ISO timestamp of the last chunk — drives the "still alive" hint. */
  at: string;
}

export type StageActivityMap = Record<string, StageActivity>;

/** A stage is treated as stalled once no chunk has arrived for this long. */
export const STALLED_AFTER_MS = 45_000;

export function activityQueryKey(projectId: string) {
  return ["project", projectId, "stage-activity"] as const;
}

export function isStalled(activity: StageActivity, now: number): boolean {
  const at = Date.parse(activity.at);
  if (Number.isNaN(at)) return false;
  return now - at > STALLED_AFTER_MS;
}

export interface BarSegments {
  /** Whole items finished, as a percentage of the bar. */
  donePct: number;
  /** The partly-streamed current item, rendered as a lighter trailing segment. */
  inFlightPct: number;
}

/**
 * Split a progress bar into settled and in-flight segments.
 *
 * The in-flight segment is one item's worth at most, so a streaming fraction
 * moves the bar continuously without ever claiming the next whole item. A
 * stalled stage drops the segment rather than freezing it mid-item, so the bar
 * doesn't imply progress that isn't happening.
 */
export function barSegments(
  itemsDone: number,
  itemsTotal: number,
  activity: StageActivity | undefined,
  now: number,
): BarSegments {
  if (itemsTotal <= 0) return { donePct: 0, inFlightPct: 0 };
  const donePct = Math.min(100, (itemsDone / itemsTotal) * 100);
  if (!activity || activity.fraction === null || isStalled(activity, now)) {
    return { donePct, inFlightPct: 0 };
  }
  const inFlightPct = Math.min(
    100 - donePct,
    (activity.fraction / itemsTotal) * 100,
  );
  return { donePct, inFlightPct: Math.max(0, inFlightPct) };
}

/**
 * Fold one event into the activity map. Returns the same reference when nothing
 * changed so React can skip the re-render.
 */
export function reduceStageActivity(
  current: StageActivityMap,
  event: PipelineEvent,
): StageActivityMap {
  if (!event.stage) return current;

  // A stage that begins, ends, or dies has no in-flight item left to describe.
  if (
    event.type === "stage_begin" ||
    event.type === "stage_complete" ||
    event.type === "stage_fail"
  ) {
    if (!(event.stage in current)) return current;
    const next = { ...current };
    delete next[event.stage];
    return next;
  }

  if (event.type !== "stage_activity") return current;

  return {
    ...current,
    [event.stage]: {
      fraction: typeof event.fraction === "number" ? event.fraction : null,
      detail: event.detail ?? null,
      at: event.at ?? new Date().toISOString(),
    },
  };
}

export function applyStageActivityEvent(
  queryClient: QueryClient,
  projectId: string,
  event: PipelineEvent,
): void {
  queryClient.setQueryData<StageActivityMap>(
    activityQueryKey(projectId),
    (current) => reduceStageActivity(current ?? {}, event),
  );
}

import type { PipelineEvent, ProjectStatus, StageInfo } from "../types/api";

const CHECKPOINT_STAGES = new Set(["extract", "style", "cast", "draw"]);

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function applyStageEventToProjectStatus(
  current: ProjectStatus | undefined,
  event: PipelineEvent,
): ProjectStatus | undefined {
  if (!current || !event.stage) return current;
  if (
    event.type !== "stage_begin" &&
    event.type !== "stage_progress" &&
    event.type !== "stage_complete" &&
    event.type !== "stage_fail"
  ) {
    return current;
  }

  const existing = current.stages[event.stage];
  if (!existing) return current;

  const next: StageInfo = { ...existing };

  if (event.type === "stage_begin") {
    next.status = "running";
    next.items_done = 0;
    if (isFiniteNumber(event.total)) {
      next.items_total = event.total;
    }
    next.items_failed = [];
    next.error = null;
    next.finished_at = null;
    next.stale = false;
  } else if (event.type === "stage_progress") {
    next.status = "running";
    if (isFiniteNumber(event.done)) {
      next.items_done = event.done;
    }
    if (isFiniteNumber(event.total)) {
      next.items_total = event.total;
    }
    next.error = null;
    next.stale = false;
  } else if (event.type === "stage_complete") {
    next.status = CHECKPOINT_STAGES.has(event.stage) ? "awaiting_review" : "complete";
    if (isFiniteNumber(event.done)) {
      next.items_done = event.done;
    }
    if (isFiniteNumber(event.total)) {
      next.items_total = event.total;
    }
    next.error = null;
    next.finished_at = new Date().toISOString();
    next.stale = false;
  } else {
    next.status = "failed";
    next.error = event.message ?? existing.error;
    next.finished_at = new Date().toISOString();
    next.stale = false;
  }

  return {
    ...current,
    is_running: event.type !== "stage_fail",
    stages: { ...current.stages, [event.stage]: next },
  };
}

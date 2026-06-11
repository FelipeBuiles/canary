/**
 * Stage progress reconciliation — the single owner of how pipeline progress
 * reaches the query cache and the draw progress store.
 *
 * Two feeds cross this seam:
 *  - SSE events flow through `applyPipelineEvent` (called by the pipeline
 *    SSE store for every event).
 *  - The REST status poll flows through `reconcileStatusPoll` (called by
 *    `useProjectStatus` for every response).
 *
 * Rooms read the reconciled view from the query cache; nothing else may
 * patch stage progress. SSE can advance `items_done` past a stale poll, so
 * the poll path must never regress a running stage's counters.
 */
import type { QueryClient } from "@tanstack/react-query";
import { completedStageArtifactQueryKeys } from "./pipelineArtifacts";
import { applyStageEventToProjectStatus } from "./pipelineStatusEvents";
import { useDrawProgressStore } from "../store/drawProgress";
import type { PipelineEvent, ProjectStatus } from "../types/api";

export function statusQueryKey(projectId: string) {
  return ["project", projectId, "status"] as const;
}

/**
 * Merge a fresh /status poll over the cached view without letting a stale
 * poll regress counters SSE already advanced — progress never goes backward
 * while a stage is running.
 */
export function reconcileStatusPoll(
  cached: ProjectStatus | undefined,
  fresh: ProjectStatus,
): ProjectStatus {
  if (!cached) return fresh;
  const mergedStages = { ...fresh.stages };
  for (const stage of Object.keys(fresh.stages)) {
    const freshInfo = fresh.stages[stage];
    const cachedInfo = cached.stages[stage];
    if (cachedInfo && freshInfo.status === "running" && cachedInfo.items_done > freshInfo.items_done) {
      mergedStages[stage] = {
        ...freshInfo,
        items_done: cachedInfo.items_done,
        items_total: Math.max(cachedInfo.items_total, freshInfo.items_total),
      };
    }
  }
  return { ...fresh, stages: mergedStages };
}

function applyStatusPatch(queryClient: QueryClient, projectId: string, event: PipelineEvent) {
  if (!event.stage) return;
  if (
    event.type !== "stage_begin" &&
    event.type !== "stage_progress" &&
    event.type !== "stage_complete" &&
    event.type !== "stage_fail"
  ) {
    return;
  }

  const statusKey = statusQueryKey(projectId);
  queryClient.setQueryData<ProjectStatus>(statusKey, (current) =>
    applyStageEventToProjectStatus(current, event),
  );

  if (event.type === "stage_fail") {
    void queryClient.invalidateQueries({ queryKey: statusKey });
  }
  if (event.type === "stage_complete") {
    for (const queryKey of completedStageArtifactQueryKeys(projectId, event.stage)) {
      void queryClient.invalidateQueries({ queryKey });
    }
  }
}

function applyDrawProgress(queryClient: QueryClient, projectId: string, event: PipelineEvent) {
  if (event.stage !== "draw") return;
  const drawProgress = useDrawProgressStore.getState();

  if (event.type === "panel_start"
      && event.scene_id != null
      && event.panel_number != null
      && event.started_at) {
    drawProgress.applyPanelStart(projectId, event.scene_id, event.panel_number, event.started_at);
    return;
  }
  if (event.type === "panel_done"
      && event.scene_id != null
      && event.panel_number != null
      && event.status
      && event.duration_ms != null) {
    drawProgress.applyPanelDone(
      projectId,
      event.scene_id,
      event.panel_number,
      event.status,
      event.duration_ms,
      event.error ?? null,
    );
    void queryClient.invalidateQueries({ queryKey: ["project", projectId, "images"] });
    return;
  }
  if (event.type === "stage_complete" || event.type === "stage_fail") {
    drawProgress.clear(projectId);
  }
}

/** Route one SSE event into the query cache and the draw progress store. */
export function applyPipelineEvent(
  queryClient: QueryClient,
  projectId: string,
  event: PipelineEvent,
): void {
  applyStatusPatch(queryClient, projectId, event);
  applyDrawProgress(queryClient, projectId, event);
}

import type { GenerationJob, StageName } from "../types/api";

export interface StageQueue {
  state: "queued" | "starting";
  waitingFor: "cover" | "other-project" | "work";
}

/** A pending stage is only queued when an actual pipeline job says so.
 * Covers and other auxiliary jobs must never masquerade as pipeline stages.
 */
export function getStageQueue(stage: StageName, jobs: GenerationJob[] = []): StageQueue | undefined {
  const job = jobs.find((item) => item.kind === "pipeline_stage"
    && (item.stage ?? item.payload.stage) === stage
    && (item.status === "queued" || item.status === "running"));
  if (!job) return undefined;
  return {
    state: job.status === "queued" ? "queued" : "starting",
    waitingFor: job.waiting_for_other_project ? "other-project"
      : jobs.some((item) => item.kind === "project_cover" && item.status === "running") ? "cover" : "work",
  };
}

import { apiFetch } from "./client";
import type { GenerationJob } from "../types/api";

export function runPipeline(
  project: string,
  stage?: string,
  rerun?: boolean,
): Promise<{ status: string; stage: string }> {
  const params = new URLSearchParams();
  if (stage) params.set("stage", stage);
  if (rerun) params.set("rerun", "1");
  const query = params.toString();
  return apiFetch(`/projects/${encodeURIComponent(project)}/run${query ? `?${query}` : ""}`, {
    method: "POST",
  });
}

export function regenPanel(
  project: string,
  sceneId: string,
  panelNumber: number,
): Promise<{ status: string; job: GenerationJob; scene_id: string; panel_number: number; planned_panel_id?: string | null }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen?scene_id=${encodeURIComponent(sceneId)}&panel_number=${panelNumber}`,
    { method: "POST" },
  );
}

export function getGenerationJobs(
  project: string,
  ids: string[],
): Promise<{ jobs: GenerationJob[] }> {
  const params = ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&");
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/generation-jobs${params ? `?${params}` : ""}`,
  );
}

export function regenRef(
  project: string,
  charId: string,
): Promise<{ status: string; job: GenerationJob; char_id: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-ref?char_id=${encodeURIComponent(charId)}`,
    { method: "POST" },
  );
}

export function regenPlate(
  project: string,
  locId: string,
): Promise<{ status: string; job: GenerationJob; loc_id: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-plate?loc_id=${encodeURIComponent(locId)}`,
    { method: "POST" },
  );
}

export function resetStale(project: string): Promise<{ status: string; reset: string[]; message: string }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/reset-stale`, {
    method: "POST",
  });
}

export function approveStage(
  project: string,
  stage: string,
): Promise<{ status: string; stage: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/approve/${encodeURIComponent(stage)}`,
    { method: "POST" },
  );
}

export function regenExtract(
  project: string,
): Promise<{ status: string; stage: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-extract`,
    { method: "POST" },
  );
}

export function fetchStageEstimate(
  project: string,
  stage: string,
): Promise<{ stage: string; credits: number }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/estimate?stage=${encodeURIComponent(stage)}`,
  );
}

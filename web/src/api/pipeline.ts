import { apiFetch } from "./client";

export function runPipeline(
  project: string,
  stage?: string,
): Promise<{ status: string; stage: string }> {
  const params = stage ? `?stage=${encodeURIComponent(stage)}` : "";
  return apiFetch(`/projects/${encodeURIComponent(project)}/run${params}`, {
    method: "POST",
  });
}

export function regenPanel(
  project: string,
  sceneId: string,
  panelNumber: number,
): Promise<{ status: string; scene_id: string; panel_number: number }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen?scene_id=${encodeURIComponent(sceneId)}&panel_number=${panelNumber}`,
    { method: "POST" },
  );
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

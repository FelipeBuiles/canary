import { apiFetch } from "./client";
import type {
  StoryBible,
  ScreenplaySummary,
  Screenplay,
  PanelSceneSummary,
  PanelBreakdown,
  ImagePrompt,
  ImageStatus,
  ImageGenerationMeta,
} from "../types/api";

// ── Story Bible ──────────────────────────────────────────────────────────────

export function getStoryBible(project: string): Promise<StoryBible> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/story-bible`);
}

export function updateStoryBible(project: string, data: StoryBible): Promise<StoryBible> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/story-bible`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// ── Screenplays ──────────────────────────────────────────────────────────────

export function listScreenplays(project: string): Promise<ScreenplaySummary[]> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/screenplays`);
}

export function getScreenplay(
  project: string,
  sceneId: string,
): Promise<Screenplay> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/screenplays/${encodeURIComponent(sceneId)}`,
  );
}

// ── Panels ────────────────────────────────────────────────────────────────────

export function listPanelSummaries(
  project: string,
): Promise<PanelSceneSummary[]> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/panels`);
}

export function getPanelsForScene(
  project: string,
  sceneId: string,
): Promise<PanelBreakdown[]> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/panels/${encodeURIComponent(sceneId)}`,
  );
}

export function updatePanel(
  project: string,
  sceneId: string,
  panelNumber: number,
  data: PanelBreakdown,
): Promise<PanelBreakdown> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/panels/${encodeURIComponent(sceneId)}/${panelNumber}`,
    { method: "PUT", body: JSON.stringify(data) },
  );
}

// ── Prompts ───────────────────────────────────────────────────────────────────

export function listPromptSummaries(
  project: string,
): Promise<{ scene_id: string; prompt_count: number }[]> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/prompts`);
}

export function getPromptsForScene(
  project: string,
  sceneId: string,
): Promise<ImagePrompt[]> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/prompts/${encodeURIComponent(sceneId)}`,
  );
}

export function updatePrompt(
  project: string,
  sceneId: string,
  panelNumber: number,
  data: ImagePrompt,
): Promise<ImagePrompt> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/prompts/${encodeURIComponent(sceneId)}/${panelNumber}`,
    { method: "PUT", body: JSON.stringify(data) },
  );
}

// ── Images ────────────────────────────────────────────────────────────────────

export function listImages(project: string): Promise<ImageStatus[]> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/images`);
}

export async function getImageGenerationMeta(
  project: string,
  relativeImagePath: string,
): Promise<ImageGenerationMeta | null> {
  const encodedPath = `${relativeImagePath}.meta.json`
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  try {
    return await apiFetch(`/projects/${encodeURIComponent(project)}/files/${encodedPath}`);
  } catch (err) {
    if (err instanceof Error && err.message.startsWith("API 404:")) {
      return null;
    }
    throw err;
  }
}

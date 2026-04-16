import { apiFetch } from "./client";
import type {
  StoryBible,
  ScreenplaySummary,
  Screenplay,
  PanelSceneSummary,
  PanelBreakdown,
  ImagePrompt,
  ImageStatus,
} from "../types/api";

// ── Story Bible ──────────────────────────────────────────────────────────────

export function getStoryBible(project: string): Promise<StoryBible> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/story-bible`);
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

// ── Images ────────────────────────────────────────────────────────────────────

export function listImages(project: string): Promise<ImageStatus[]> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/images`);
}

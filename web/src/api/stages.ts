import { apiFetch } from "./client";
import type {
  StoryBible,
  ScreenplaySummary,
  Screenplay,
  LayoutPlan,
  NarrationDecision,
  NarrationImpact,
  PanelSceneSummary,
  PanelBreakdown,
  ImagePrompt,
  ImageStatus,
  ImageGenerationMeta,
  PanelImageVersionsResponse,
  RestorePanelImageVersionResponse,
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

export function getLayoutPlan(project: string): Promise<LayoutPlan> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/layout-plan`);
}

export function estimateNarrationDecisionImpact(
  project: string,
  beatId: string,
  patch: Partial<NarrationDecision>,
): Promise<NarrationImpact> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/layout-plan/narration-decisions/${encodeURIComponent(beatId)}/impact`,
    { method: "POST", body: JSON.stringify(patch) },
  );
}

export function updateNarrationDecision(
  project: string,
  beatId: string,
  patch: Partial<NarrationDecision>,
): Promise<{ decision: NarrationDecision; impact: NarrationImpact }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/layout-plan/narration-decisions/${encodeURIComponent(beatId)}`,
    { method: "PUT", body: JSON.stringify(patch) },
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
): Promise<{ scene_id: string; prompt_count: number; panel_numbers?: number[] }[]> {
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
  fields: Partial<ImagePrompt>,
): Promise<ImagePrompt> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/prompts/${encodeURIComponent(sceneId)}/${panelNumber}`,
    { method: "PUT", body: JSON.stringify({ fields }) },
  );
}

// ── Images ────────────────────────────────────────────────────────────────────

export function listImages(project: string): Promise<ImageStatus[]> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/images`);
}

export function acceptImagePanel(
  project: string,
  sceneId: string,
  panelNumber: number,
): Promise<{ scene_id: string; panel_number: number; accepted: boolean; accepted_at?: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/images/${encodeURIComponent(sceneId)}/${panelNumber}/accept`,
    { method: "POST" },
  );
}

export function unacceptImagePanel(
  project: string,
  sceneId: string,
  panelNumber: number,
): Promise<{ scene_id: string; panel_number: number; accepted: boolean }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/images/${encodeURIComponent(sceneId)}/${panelNumber}/accept`,
    { method: "DELETE" },
  );
}

export function flagImagePanel(
  project: string,
  sceneId: string,
  panelNumber: number,
): Promise<{ scene_id: string; panel_number: number; flagged: boolean; flagged_at?: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/images/${encodeURIComponent(sceneId)}/${panelNumber}/flag`,
    { method: "POST" },
  );
}

export function unflagImagePanel(
  project: string,
  sceneId: string,
  panelNumber: number,
): Promise<{ scene_id: string; panel_number: number; flagged: boolean }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/images/${encodeURIComponent(sceneId)}/${panelNumber}/flag`,
    { method: "DELETE" },
  );
}

export function getPrimaryRefs(project: string): Promise<{ primary_refs: Record<string, string> }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/cast/primary-refs`);
}

export function setPrimaryRef(
  project: string,
  charId: string,
  pose: string | null,
): Promise<{ char_id: string; pose: string | null; primary_refs: Record<string, string> }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/cast/${encodeURIComponent(charId)}/primary-ref`,
    { method: "PUT", body: JSON.stringify({ pose }) },
  );
}

export async function getImageGenerationMeta(
  project: string,
  relativeImagePath: string,
): Promise<ImageGenerationMeta | null> {
  const encodeProjectFile = (path: string) => path
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
  const encodedPath = encodeProjectFile(`${relativeImagePath}.meta.json`);
  try {
    return await apiFetch(`/projects/${encodeURIComponent(project)}/files/${encodedPath}`);
  } catch (err) {
    if (err instanceof Error && err.message.startsWith("API 404:")) {
      const failurePath = encodeProjectFile(`${relativeImagePath}.failure.json`);
      try {
        return await apiFetch(`/projects/${encodeURIComponent(project)}/files/${failurePath}`);
      } catch (failureErr) {
        if (failureErr instanceof Error && failureErr.message.startsWith("API 404:")) {
          return null;
        }
        throw failureErr;
      }
    }
    throw err;
  }
}

export function getPanelImageVersions(
  project: string,
  sceneId: string,
  panelNumber: number,
): Promise<PanelImageVersionsResponse> {
  return apiFetch<PanelImageVersionsResponse>(
    `/projects/${encodeURIComponent(project)}/images/${encodeURIComponent(sceneId)}/${panelNumber}/versions`,
  ).catch((err) => {
    if (err instanceof Error && err.message.startsWith("API 404:")) {
      return {
        scene_id: sceneId,
        panel_number: panelNumber,
        has_history: false,
        versions: [],
      };
    }
    throw err;
  });
}

export function restorePanelImageVersion(
  project: string,
  sceneId: string,
  panelNumber: number,
  version: number,
): Promise<RestorePanelImageVersionResponse> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/images/${encodeURIComponent(sceneId)}/${panelNumber}/versions/${version}/restore`,
    { method: "POST" },
  );
}

import { apiFetch, isNotFoundError } from "./client";
import { projectPath, seriesPath } from "./projectScope";
import type {
  StoryBible,
  StoryDecision,
  AdaptationBrief,
  ImageGenerationMeta,
} from "../types/api";

// ── Story Bible ──────────────────────────────────────────────────────────────

export function getStoryBible(project: string): Promise<StoryBible> {
  return apiFetch(`${seriesPath(project)}/story-bible`);
}

export function getStory(project: string): Promise<StoryDecision> {
  return apiFetch(`${projectPath(project)}/story`);
}

export function updateBrief(
  project: string,
  expectedRevision: number,
  changes: Partial<AdaptationBrief>,
): Promise<AdaptationBrief> {
  return apiFetch(`${projectPath(project)}/brief`, {
    method: "PUT",
    body: JSON.stringify({
      expected_revision: expectedRevision,
      changes,
    }),
  });
}

export function getPrimaryRefs(project: string): Promise<{ primary_refs: Record<string, string> }> {
  return apiFetch(`${seriesPath(project)}/cast/primary-refs`);
}

export function setPrimaryRef(
  project: string,
  charId: string,
  pose: string | null,
): Promise<{ char_id: string; pose: string | null; primary_refs: Record<string, string> }> {
  return apiFetch(
    `${seriesPath(project)}/cast/${encodeURIComponent(charId)}/primary-ref`,
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
    return await apiFetch(`${seriesPath(project)}/files/${encodedPath}`);
  } catch (err) {
    if (isNotFoundError(err)) {
      const failurePath = encodeProjectFile(`${relativeImagePath}.failure.json`);
      try {
        return await apiFetch(`${seriesPath(project)}/files/${failurePath}`);
      } catch (failureErr) {
        if (isNotFoundError(failureErr)) {
          return null;
        }
        throw failureErr;
      }
    }
    throw err;
  }
}

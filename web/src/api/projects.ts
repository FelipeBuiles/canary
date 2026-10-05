import { apiFetch } from "./client";
import { projectPath, seriesPath } from "./projectScope";
import type { CostEstimate, GenerationJob, ProjectSummary, ProjectStatus, ConfigOverrides, ShortStory, SourcePreview } from "../types/api";

export function listProjects(): Promise<ProjectSummary[]> {
  return apiFetch<ProjectSummary[]>("/projects/");
}

export function getProjectStatus(id: string): Promise<ProjectStatus> {
  return apiFetch<ProjectStatus>(`${projectPath(id)}/status`);
}

export function renameProject(id: string, name: string): Promise<{ id: string; project_name: string }> {
  return apiFetch(seriesPath(id), {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });
}

export function createProject(
  file: File,
  name: string,
  configOverrides?: Partial<ConfigOverrides>,
): Promise<{ id: string; name: string; project_name: string; status: string; part_id: string }> {
  const form = new FormData();
  form.append("file", file);
  form.append("name", name);
  if (configOverrides) {
    form.append("config_overrides", JSON.stringify(configOverrides));
  }
  return apiFetch("/projects/", {
    method: "POST",
    headers: {},  // let browser set Content-Type for multipart
    body: form,
  });
}

/** Read a manuscript and report its parts; nothing is stored. */
export function previewSource(file: File, signal?: AbortSignal): Promise<SourcePreview> {
  const form = new FormData();
  form.append("file", file);
  return apiFetch("/projects/source-preview", { method: "POST", headers: {}, body: form, signal });
}

export function deleteProject(id: string): Promise<void> {
  return apiFetch(seriesPath(id), {
    method: "DELETE",
  });
}

export function generateProjectCover(
  projectId: string,
): Promise<{ status: string; path: string; job: GenerationJob | null }> {
  return apiFetch(`${projectPath(projectId)}/cover`, {
    method: "POST",
  });
}

export function fetchProjectCoverEstimate(projectId: string): Promise<CostEstimate> {
  return apiFetch(`${projectPath(projectId)}/cover-estimate`);
}

export function listShortStories(): Promise<ShortStory[]> {
  return apiFetch<ShortStory[]>("/projects/short-stories");
}

export function readShortStory(code: string, signal?: AbortSignal): Promise<{ code: string; text: string }> {
  return apiFetch<{ code: string; text: string }>(`/projects/short-stories/${encodeURIComponent(code)}`, { signal });
}

export function importStory(
  name: string,
  urlOrCode: string,
  configOverrides?: Partial<ConfigOverrides>,
): Promise<{ id: string; name: string; project_name: string; status: string }> {
  return apiFetch("/projects/import-story", {
    method: "POST",
    body: JSON.stringify({
      name,
      url_or_code: urlOrCode,
      config_overrides: configOverrides ? JSON.stringify(configOverrides) : null,
    }),
  });
}

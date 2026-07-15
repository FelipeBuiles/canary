import { apiFetch } from "./client";
import type { CostEstimate, GenerationJob, ProjectSummary, ProjectStatus, ConfigOverrides, ShortStory } from "../types/api";

export function listProjects(): Promise<ProjectSummary[]> {
  return apiFetch<ProjectSummary[]>("/projects/");
}

export function getProjectStatus(id: string): Promise<ProjectStatus> {
  return apiFetch<ProjectStatus>(`/projects/${encodeURIComponent(id)}/status`);
}

export function createProject(
  file: File,
  name: string,
  configOverrides?: Partial<ConfigOverrides>,
): Promise<{ id: string; name: string; project_name: string; status: string }> {
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

export function deleteProject(id: string): Promise<void> {
  return apiFetch(`/projects/${encodeURIComponent(id)}`, {
    method: "DELETE",
  });
}

export function generateProjectCover(
  projectId: string,
): Promise<{ status: string; path: string; job: GenerationJob | null }> {
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/cover`, {
    method: "POST",
  });
}

export function fetchProjectCoverEstimate(projectId: string): Promise<CostEstimate> {
  return apiFetch(`/projects/${encodeURIComponent(projectId)}/cover-estimate`);
}

export function listShortStories(): Promise<ShortStory[]> {
  return apiFetch<ShortStory[]>("/projects/short-stories");
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

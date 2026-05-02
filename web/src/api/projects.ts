import { apiFetch } from "./client";
import type { GenerationJob, ProjectSummary, ProjectStatus, ConfigOverrides } from "../types/api";

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

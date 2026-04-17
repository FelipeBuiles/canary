import { apiFetch } from "./client";
import type { GenerationJob, ProjectSummary, ProjectStatus, ConfigOverrides } from "../types/api";

export function listProjects(): Promise<ProjectSummary[]> {
  return apiFetch<ProjectSummary[]>("/projects/");
}

export function getProjectStatus(name: string): Promise<ProjectStatus> {
  return apiFetch<ProjectStatus>(`/projects/${encodeURIComponent(name)}/status`);
}

export function createProject(
  file: File,
  name: string,
  configOverrides?: Partial<ConfigOverrides>,
): Promise<{ name: string; project_name: string; status: string }> {
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

export function generateProjectCover(
  project: string,
): Promise<{ status: string; path: string; job: GenerationJob | null }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/cover`, {
    method: "POST",
  });
}

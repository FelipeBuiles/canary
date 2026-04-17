import { apiFetch } from "./client";
import type { ConfigOverrides } from "../types/api";

export interface ProjectConfig extends ConfigOverrides {
  target_language: "en" | "es" | "fr";
}

export function getProjectConfig(project: string): Promise<ProjectConfig> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/config/`);
}

export function updateProjectConfig(
  project: string,
  data: Partial<ProjectConfig>,
): Promise<ProjectConfig> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/config/`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

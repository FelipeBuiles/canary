import { apiFetch } from "./client";
import type { ProjectSummary, ProjectStatus } from "../types/api";

export function listProjects(): Promise<ProjectSummary[]> {
  return apiFetch<ProjectSummary[]>("/projects/");
}

export function getProjectStatus(name: string): Promise<ProjectStatus> {
  return apiFetch<ProjectStatus>(`/projects/${encodeURIComponent(name)}/status`);
}

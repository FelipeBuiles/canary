import { apiFetch } from "./client";
import type { CostEstimate, GenerationJob } from "../types/api";

export interface StyleSuggestion {
  index: number;
  label: string;
  template: string;
  has_sample: boolean;
  is_active: boolean;
}

export interface StylesData {
  suggestions: StyleSuggestion[];
  active_index: number | null;
}

export function getStyles(project: string): Promise<StylesData> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/styles`);
}

export function suggestStyles(project: string): Promise<{ status: string }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/styles/suggest`, {
    method: "POST",
  });
}

export function fetchSuggestStylesEstimate(project: string): Promise<CostEstimate> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/styles/suggest-estimate`);
}

export function generateStyleSamples(
  project: string,
  indices: number[],
): Promise<{ status: string; indices: number[]; jobs: GenerationJob[] }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/styles/generate-samples`, {
    method: "POST",
    body: JSON.stringify({ indices }),
  });
}

export function setActiveStyle(
  project: string,
  index: number,
): Promise<{ status: string; index: number; style_template: string }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/styles/active`, {
    method: "PATCH",
    body: JSON.stringify({ index }),
  });
}

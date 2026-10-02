import { apiFetch } from "./client";
import { seriesPath } from "./projectScope";
import type { CostEstimate, GenerationJob } from "../types/api";

export interface StyleSuggestion {
  id: string;
  index: number;
  label: string;
  /** Presentation name from the proof-naming pass or an author rename. */
  display_label?: string;
  hidden?: boolean;
  origin: string;
  role: string | null;
  medium: string;
  palette: string;
  line_rendering: string;
  lighting_value: string;
  sequential_art_strengths: string;
  story_fit: string;
  risk: string;
  template: string;
  visual_logic?: "photographic" | "realistic_illustration" | "stylized" | "graphic" | null;
  proportion_family?: "naturalistic" | "heroic" | "elongated" | "compact" | "caricatured" | "geometric" | null;
  character_design?: string;
  style_reference_mode?: "faithful" | "variation";
  sample_preview_url?: string | null;
  lettering_source?: "generated" | "preset";
  has_sample: boolean;
  generation_status?: "not_requested" | "queued" | "running" | "complete" | "failed";
  sample_stale: boolean;
  has_style_reference: boolean;
  has_validation: boolean;
  validation_url: string | null;
  is_active: boolean;
}

export interface StylesData {
  is_generating?: boolean;
  /** A suggestion batch owns the portfolio; single proofs may still queue. */
  is_suggesting?: boolean;
  suggestions: StyleSuggestion[];
  active_index: number | null;
  active_id: string | null;
}

export interface StyleDirectionResponse {
  status: "queued";
  with_neighbors: boolean;
  estimate: CostEstimate;
  direction: {
    id: string;
    text: string;
    has_image: boolean;
    image_supported: boolean;
  };
  suggestion: Omit<StyleSuggestion, "has_style_reference" | "has_validation" | "validation_url" | "is_active"> &
    Partial<Pick<StyleSuggestion, "has_style_reference" | "has_validation" | "validation_url" | "is_active">>;
  job: GenerationJob;
}

export interface StyleDirectionEstimate extends CostEstimate {
  estimates: {
    faithful: CostEstimate;
    neighbors: CostEstimate;
    faithful_with_neighbors: CostEstimate;
  };
  estimates_without_reference: {
    faithful: CostEstimate;
    neighbors: CostEstimate;
    faithful_with_neighbors: CostEstimate;
  };
  estimates_with_reference: {
    faithful: CostEstimate;
    neighbors: CostEstimate;
    faithful_with_neighbors: CostEstimate;
  };
  max_upload_bytes: number;
  accepted_image_types: string[];
  image_reference_supported: boolean;
}

export function getStyles(project: string): Promise<StylesData> {
  return apiFetch(`${seriesPath(project)}/styles`);
}

export function suggestStyles(project: string, directionId?: string): Promise<{ status: string; job?: GenerationJob }> {
  return apiFetch(`${seriesPath(project)}/styles/suggest`, {
    method: "POST",
    body: directionId ? JSON.stringify({ direction_id: directionId }) : undefined,
  });
}

export function createStyleDirection(
  project: string,
  input: { direction: string; image: File | null; withNeighbors: boolean },
): Promise<StyleDirectionResponse> {
  const form = new FormData();
  if (input.direction) form.append("direction_text", input.direction);
  if (input.image) form.append("image", input.image);
  form.append("with_neighbors", String(input.withNeighbors));
  return apiFetch(`${seriesPath(project)}/styles/direction`, {
    method: "POST",
    headers: {},
    body: form,
  });
}

export function fetchSuggestStylesEstimate(project: string): Promise<CostEstimate> {
  return apiFetch(`${seriesPath(project)}/styles/suggest-estimate`);
}

export function fetchStyleSampleEstimate(project: string): Promise<CostEstimate> {
  return apiFetch(`${seriesPath(project)}/styles/sample-estimate`);
}

export function fetchStyleDirectionEstimate(project: string): Promise<StyleDirectionEstimate> {
  return apiFetch(`${seriesPath(project)}/styles/direction-estimate`);
}

export function generateStyleSamples(
  project: string,
  ids: string[],
): Promise<{ status: string; indices: number[]; jobs: GenerationJob[] }> {
  return apiFetch(`${seriesPath(project)}/styles/generate-samples`, {
    method: "POST",
    body: JSON.stringify({ ids }),
  });
}

export function generateStyleValidation(
  project: string,
  id: string,
): Promise<{ status: "queued"; id: string; url: string; job: GenerationJob }> {
  return apiFetch(`${seriesPath(project)}/styles/validation`, {
    method: "POST",
    body: JSON.stringify({ id }),
  });
}

export function isAuthorDirection(suggestion: Pick<StyleSuggestion, "origin">): boolean {
  return suggestion.origin.startsWith("user_");
}

export function proofImageUrl(projectName: string, suggestion: Pick<StyleSuggestion, "sample_preview_url" | "index">): string {
  return suggestion.sample_preview_url
    ?? `/api${seriesPath(projectName)}/files/samples/style_${suggestion.index}.png`;
}

export function styleName(suggestion: Pick<StyleSuggestion, "label" | "display_label">): string {
  return suggestion.display_label || suggestion.label;
}

export function updateStylePresentation(
  project: string,
  id: string,
  changes: { display_label?: string; hidden?: boolean },
): Promise<{ suggestion: StyleSuggestion }> {
  return apiFetch(`${seriesPath(project)}/styles/${encodeURIComponent(id)}`, {
    method: "PATCH",
    body: JSON.stringify(changes),
  });
}

export function setActiveStyle(
  project: string,
  id: string,
): Promise<{ status: string; id: string; index: number; style_template: string }> {
  return apiFetch(`${seriesPath(project)}/styles/active`, {
    method: "PATCH",
    body: JSON.stringify({ id }),
  });
}

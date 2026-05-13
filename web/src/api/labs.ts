import { apiFetch } from "./client";

export type LabsTier = "fast" | "balanced" | "premium";

export interface LabsModel {
  id: string;
  label: string;
  provider: "fal" | "together" | "litellm";
  endpoint: string;
  tier: LabsTier;
  multi_ref: boolean;
  max_refs: number;
  style_refs: boolean;
  approx_cost: number | null;
  notes: string | null;
}

export interface LabsReferenceImage {
  filename: string;
  label: string;
  role: string;
  url: string;
}

export interface LabsPanel {
  idx: number;
  label: string;
  prompt: string;
  width: number;
  height: number;
}

export interface LabsFixtureScene {
  id: string;
  label: string;
  description: string;
  default_style_template: string;
  reference_images: LabsReferenceImage[];
  panels: LabsPanel[];
}

export interface LabsImportableProject {
  id: string;
  name: string;
  scene_count: number;
}

export interface LabsProjectScene {
  scene_id: string;
  panel_count: number;
  first_prompt_preview: string;
}

export interface LabsImportedScene {
  label: string;
  style_template: string;
  panels: LabsPanel[];
  imported_reference_paths: string[];
}

export type LabsCellStatus = "pending" | "ok" | "failed";

export interface LabsCell {
  status: LabsCellStatus;
  image_url?: string;
  latency_ms?: number;
  cost_usd?: number | null;
  cost_source?: string | null;
  provider_model?: string | null;
  pricing_snapshot?: string | null;
  error?: string;
  provider_request_id?: string | null;
  started_at?: string;
}

export interface LabsRunPanelResult {
  idx: number;
  label: string;
  prompt: string;
  cells: Record<string, LabsCell>;
}

export interface LabsRunDetail {
  run_id: string;
  label: string;
  status: "running" | "complete" | "failed" | "cancelled";
  created_at: string;
  finished_at: string | null;
  cells_total: number;
  cells_done: number;
  total_cost_usd: number;
  model_ids: string[];
  style_template: string;
  reference_image_names: string[];
  error: string | null;
  panels: LabsRunPanelResult[];
}

export interface LabsRunSummary {
  run_id: string;
  created_at: string;
  label: string;
  model_ids: string[];
  panel_count: number;
  status: string;
  total_cost_usd?: number | null;
}

export type LabsReferenceSource = "fixture" | "imported" | "none";

export interface LabsRunCreatePayload {
  label: string;
  model_ids: string[];
  style_template: string;
  panels: { idx: number; label: string; prompt: string; width: number; height: number }[];
  reference_source: LabsReferenceSource;
  reference_image_paths?: string[];
}

export function listLabsModels(): Promise<{ models: LabsModel[] }> {
  return apiFetch("/labs/models");
}

export function getDefaultFixture(): Promise<LabsFixtureScene> {
  return apiFetch("/labs/fixtures/default");
}

export function listImportableProjects(): Promise<{ projects: LabsImportableProject[] }> {
  return apiFetch("/labs/projects");
}

export function listProjectScenes(projectId: string): Promise<{ scenes: LabsProjectScene[] }> {
  return apiFetch(`/labs/projects/${encodeURIComponent(projectId)}/scenes`);
}

export function importProjectScene(
  projectId: string,
  body: { scene_id: string; panel_limit?: number },
): Promise<LabsImportedScene> {
  return apiFetch(`/labs/projects/${encodeURIComponent(projectId)}/import-scene`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function createLabsRun(payload: LabsRunCreatePayload): Promise<{ run_id: string; status: string }> {
  return apiFetch("/labs/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function listLabsRuns(): Promise<{ runs: LabsRunSummary[] }> {
  return apiFetch("/labs/runs");
}

export function getLabsRun(runId: string): Promise<LabsRunDetail> {
  return apiFetch(`/labs/runs/${encodeURIComponent(runId)}`);
}

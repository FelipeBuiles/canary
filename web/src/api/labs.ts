import { apiFetch } from "./client";

/**
 * Local-development experiments. API calls cost operator USD; subscription calls
 * use the local Claude or Codex allowance. Neither ever touches account credits.
 */

export type LabsFunding = "api" | "codex_subscription" | "claude_subscription";

export interface LabsProject {
  id: string;
  part_id?: string | null;
  title: string;
  statuses: Record<string, string>;
  words: number | null;
}

export interface ImageTarget {
  id: string;
  label: string;
  provider: string;
  funding: LabsFunding;
  available: boolean;
}

export type ImagePrompt =
  | "production"
  | "restructured"
  | "sheet_form"
  | "sheet_formation";

export interface ImageArm {
  target: string;
  prompt: ImagePrompt;
}

export interface ImageItem {
  id: string;
  kind: "asset" | "page";
  label: string;
  recorded_at?: string | null;
  recorded_route?: string | null;
  references?: number;
  /** Project-relative path of the recorded output, for a thumbnail. */
  preview?: string;
}

export interface ArmPreview {
  error: string | null;
  prompt?: string;
  chars?: number;
  width?: number;
  height?: number;
  references?: number;
  /** Anchors, style or lettering the production prompt carries that this arm drops. */
  missing_verbatim?: string[];
  estimated_cost_usd?: number | null;
  /** This request priced at API rates, even when a subscription runs it. */
  api_equivalent_usd?: number | null;
}

export interface ImageEstimate {
  estimated_cost_usd: number;
  calls: { api: number; subscription: number };
  problems: { item: string; arm: number; error: string }[];
}

export interface StageModelArm {
  id: string;
  /** The arm's default model, for every stage it doesn't override. */
  model: string;
  /** Per-stage overrides, so one arm can, say, Adapt on one model and Plan on another. */
  stage_models?: Record<string, string>;
  reasoning_efforts: Record<string, string>;
}

export interface StageModelOption {
  id: string;
  label: string;
  provider: string;
  funding: LabsFunding;
  available: boolean;
  reasoning_options: string[];
  default_reasoning: string;
}

export interface StageModelOptions {
  models: StageModelOption[];
  default_models: string[];
  phases: Record<string, string[]>;
}

export type LabsRunStatus = "running" | "complete" | "failed" | "interrupted";

export interface LabsRunSummary {
  run_id: string;
  kind: "image_compare" | "stage_models" | "modernize";
  label: string;
  status: LabsRunStatus;
  created_at: string;
  finished_at: string | null;
  total_cost_usd: number | null;
  cell_count: number;
}

export interface ImageCell {
  cell_id: string;
  item: string;
  arm: number;
  target: string;
  prompt: ImagePrompt;
  funding: LabsFunding;
  status: "running" | "ok" | "failed";
  prompt_file?: string;
  prompt_chars?: number;
  estimated_cost_usd?: number | null;
  /** Approximate API price of this request, for comparing subscription arms on cost. */
  api_equivalent_usd?: number | null;
  /** "WIDTHxHEIGHT" the request asked for, and what the model returned. */
  requested_size?: string;
  output_size?: string | null;
  input_sha256?: string;
  /** Earlier failed attempts of this cell, oldest first. */
  attempts?: { started_at?: string; latency_ms?: number; error?: string }[];
  image?: string;
  latency_ms?: number;
  cost_usd?: number | null;
  error?: string;
}

export interface StageResult {
  stage: string;
  status: string;
  error: string | null;
  seconds: number;
  calls: number;
  input_tokens: number;
  cached_input_tokens: number;
  output_tokens: number;
  cost_usd: number;
  unpriced_calls: number;
  /** Recorded tokens priced at the model's API rates on Canary's route; null if unpriced. */
  api_equivalent_usd?: number | null;
  models: string[];
  funding: string[];
  counts?: Record<string, number>;
  validation?: { attempts: number | null; invariant_failures: number; editorial_issues: number; blocking_issues: number };
  artifact?: string;
}

export interface StageModelCell {
  reasoning_efforts?: Record<string, string>;
  /** The model each stage ran on; absent on runs recorded before mixed arms. */
  stage_models?: Record<string, string>;
  variant?: string;
  cell_id: string;
  phase: string;
  model: string;
  funding: LabsFunding;
  status: "running" | "ok" | "failed";
  workspace: string;
  stages: StageResult[];
  seconds?: number;
  cost_usd?: number;
  api_equivalent_usd?: number | null;
  error?: string;
  input_sha256?: string;
  /** Earlier failed attempts of this arm, oldest first, each with its own workspace and spend. */
  attempts?: {
    started_at?: string;
    seconds?: number;
    cost_usd?: number | null;
    api_equivalent_usd?: number | null;
    error?: string | null;
    workspace: string;
    stages?: StageResult[];
  }[];
}

export type ModernizeIntensity = "light" | "moderate" | "contemporary";
export type ModernizeScope = "dialogue" | "narration" | "both";
export type ModernizeSensitive = "keep" | "soften" | "remove";

export interface ModernizeControls {
  intensity: ModernizeIntensity;
  scope: ModernizeScope;
  sensitive: ModernizeSensitive;
  keep_setting: boolean;
  /** Balloon-length dialogue, drawable narration, and named referents for panel-by-panel reading. */
  comic_ready: boolean;
  notes: string;
}

export interface ModernizeArm {
  id: string;
  model: string;
  reasoning?: string;
}

export interface ModernizeOptions {
  models: StageModelOption[];
  intensities: ModernizeIntensity[];
  scopes: ModernizeScope[];
  sensitive: ModernizeSensitive[];
  max_words: number;
  max_arms: number;
}

export interface ModernizeExcerpt {
  start: number;
  end: number;
  words: number;
  total_paragraphs: number;
  total_words: number;
  paragraphs: string[];
}

/** The passage: a manuscript excerpt (start + max_words) or pasted text. */
export type ModernizeSource =
  | { part_id?: string | null; start: number; max_words: number; text?: undefined }
  | { text: string };

export interface ModernizeRequest {
  project: string;
  controls: ModernizeControls;
  arms: ModernizeArm[];
}

export interface ModernizeChange {
  paragraph: number | null;
  original: string;
  revised: string;
  category: "archaic" | "offensive" | "clarity" | "idiom" | "tightened" | "inferred";
  note: string;
}

export interface ModernizeChecks {
  changed_paragraphs: number;
  missing_paragraphs: number[];
  extra_paragraphs: number[];
  words_before: number;
  words_after: number;
  dialogue_edits: number[];
  narration_edits: number[];
  /** Paragraphs edited outside the chosen scope; quote detection is heuristic. */
  scope_violations: number[];
  /** Reading load before and after; absent on runs recorded before these checks. */
  comic_before?: ModernizeComicMetrics;
  comic_after?: ModernizeComicMetrics;
}

export interface ModernizeComicMetrics {
  avg_sentence_words: number;
  longest_speech_words: number;
  /** Quoted speeches over 25 words, which crowd a balloon. */
  long_speeches: number;
}

export interface ModernizeCell {
  cell_id: string;
  arm: string;
  model: string;
  reasoning: string;
  funding: LabsFunding;
  status: "running" | "ok" | "failed";
  paragraphs?: string[];
  changes?: ModernizeChange[];
  checks?: ModernizeChecks;
  seconds?: number;
  cost_usd?: number;
  usage?: { calls: number; input_tokens: number; output_tokens: number; cost_usd: number; unpriced_calls: number; api_equivalent_usd: number | null };
  error?: string;
  attempts?: { started_at?: string; seconds?: number; error?: string | null }[];
}

export interface LabsRunDetail extends Omit<LabsRunSummary, "cell_count"> {
  spec: Record<string, unknown>;
  error: string | null;
  cells: (ImageCell | StageModelCell | ModernizeCell)[];
}

export type LabsRunCreatePayload =
  | { kind: "image_compare"; label?: string; project: string; items: string[]; arms: ImageArm[] }
  | { kind: "stage_models"; label?: string; project: string; part_id?: string | null; phases: string[]; arms: StageModelArm[] }
  | ({ kind: "modernize"; label?: string } & ModernizeRequest & ModernizeSource);

export function labsRunFileUrl(runId: string, path: string): string {
  return `/api/labs/runs/${encodeURIComponent(runId)}/files/${path.split("/").map(encodeURIComponent).join("/")}`;
}

export function listLabsProjects(): Promise<{ projects: LabsProject[] }> {
  return apiFetch("/labs/projects");
}

export function getImageCompareOptions(): Promise<{ targets: ImageTarget[]; prompts: ImagePrompt[] }> {
  return apiFetch("/labs/image-compare/options");
}

export function listImageItems(project: string): Promise<{ items: ImageItem[] }> {
  return apiFetch(`/labs/image-compare/projects/${encodeURIComponent(project)}/items`);
}

export function previewImageArms(body: { project: string; item: string; arms: ImageArm[] }): Promise<{ arms: ArmPreview[] }> {
  return apiFetch("/labs/image-compare/preview", { method: "POST", body: JSON.stringify(body) });
}

export function estimateImageCompare(body: { project: string; items: string[]; arms: ImageArm[] }): Promise<ImageEstimate> {
  return apiFetch("/labs/image-compare/estimate", { method: "POST", body: JSON.stringify(body) });
}

export function getStageModelOptions(): Promise<StageModelOptions> {
  return apiFetch("/labs/stage-models/options");
}

export function estimateStageModels(
  body: { project: string; part_id?: string | null; phases: string[]; arms: StageModelArm[] },
): Promise<{ estimated_cost_usd: Record<string, number | null> }> {
  return apiFetch("/labs/stage-models/estimate", { method: "POST", body: JSON.stringify(body) });
}

export function getModernizeOptions(): Promise<ModernizeOptions> {
  return apiFetch("/labs/modernize/options");
}

export function getModernizeExcerpt(
  project: string, query: { part_id?: string | null; start: number; max_words: number },
): Promise<ModernizeExcerpt> {
  const params = new URLSearchParams({ start: String(query.start), max_words: String(query.max_words) });
  if (query.part_id) params.set("part_id", query.part_id);
  return apiFetch(`/labs/modernize/projects/${encodeURIComponent(project)}/excerpt?${params}`);
}

export function estimateModernize(
  body: ModernizeRequest & ModernizeSource,
): Promise<{
  estimated_cost_usd: Record<string, number | null>;
  /** "history" prices from earlier runs of the same model and reasoning; "heuristic" before any exist. */
  estimate_basis: Record<string, { basis: "history" | "heuristic"; runs: number }>;
  words: number;
  paragraphs: number;
}> {
  return apiFetch("/labs/modernize/estimate", { method: "POST", body: JSON.stringify(body) });
}

/** The run's frozen passage, as every arm received it. */
export function getModernizeSource(runId: string): Promise<{ paragraphs: string[]; words: number; origin: string }> {
  return apiFetch(`/labs/runs/${encodeURIComponent(runId)}/files/source.json`);
}

export function createLabsRun(payload: LabsRunCreatePayload): Promise<LabsRunDetail> {
  return apiFetch("/labs/runs", { method: "POST", body: JSON.stringify(payload) });
}

export function listLabsRuns(): Promise<{ runs: LabsRunSummary[] }> {
  return apiFetch("/labs/runs");
}

export function getLabsRun(runId: string): Promise<LabsRunDetail> {
  return apiFetch(`/labs/runs/${encodeURIComponent(runId)}`);
}

/** Retry failed cells with their recorded inputs: image cells resend the same request, text arms rerun
 * their phase. Omit ``cells`` to retry every failure. */
export function retryLabsCells(runId: string, cells?: string[]): Promise<{ status: string; cells: string[] }> {
  return apiFetch(`/labs/runs/${encodeURIComponent(runId)}/retry`, {
    method: "POST", body: JSON.stringify(cells ? { cells } : {}),
  });
}

export function deleteLabsRun(runId: string): Promise<{ status: string }> {
  return apiFetch(`/labs/runs/${encodeURIComponent(runId)}`, { method: "DELETE" });
}

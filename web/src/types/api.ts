export type StageName =
  | "extract"
  | "brief"
  | "style"
  | "cast"
  | "adapt"
  | "plan"
  | "draw"
  | "finish";

export type StageStatus =
  | "pending"
  | "running"
  | "awaiting_review"
  | "complete"
  | "failed";

export interface ConfigOverrides {
  style_template?: string;
  image_provider?: "gemini" | "openai" | "openrouter" | "together";
  image_model?: string;
  target_language?: "en" | "es" | "fr";
  dev_mode?: boolean;
  quality_preset?: "fast" | "balanced" | "quality" | null;
  extraction_model?: string;
  dev_image_scale?: number;
  dev_image_steps?: number;
  dev_image_concurrency?: number;
  fallback_image_model?: string;
  image_width?: number;
  image_height?: number;
  image_steps?: number;
  image_quality?: "auto" | "low" | "medium" | "high";
  flux_guidance_scale?: number;
  image_model_aliases?: string[];
}

export interface InFlightPage {
  page_number: number;
  started_at: string;
}

export interface StageInfo {
  status: StageStatus;
  items_done: number;
  items_total: number;
  items_failed: string[];
  approved: boolean | null;
  cost_credits: number;
  estimated_cost_credits: number;
  error: string | null;
  // Structured credit-failure detail. Set only when the stage failed because
  // the user's balance couldn't cover the reservation. Drives the in-room
  // CreditsGate panel (see useNeedsCredits).
  error_code: string | null;
  balance_credits: number | null;
  required_credits: number | null;
  shortfall_credits: number | null;
  started_at: string | null;
  finished_at: string | null;
  last_progress_at: string | null;
  stale: boolean;
  in_flight: InFlightPage[];
}

export interface ProjectSummary {
  id: string;
  name: string;
  project_name: string;
  author?: string | null;
  created_at: string;
  total_cost_credits: number;
  furthest_stage: string | null;
  is_running: boolean;
  has_cover: boolean;
  cover_job: GenerationJob | null;
  incompatible?: boolean;
  incompatibility_reason?: string | null;
}

export interface ProjectStatus {
  id: string;
  project_name: string;
  created_at: string;
  total_cost_credits: number;
  misc_cost_credits: number;
  total_estimated_cost_credits: number;
  is_running: boolean;
  has_cover: boolean;
  style_selected: boolean;
  is_public: boolean;
  share_token: string | null;
  page_count?: number;
  page_issue_summary?: PageIssueSummary;
  finish_ready?: boolean;
  stages: Record<string, StageInfo>;
}

export interface CreditBalance {
  balance_credits: number;
}

export type CostConfidence = "low_variance" | "usually_within_estimate" | "variable";

export interface CostEstimate {
  estimate_credits: number;
  reserved_credits: number | null;
  reservation_multiplier: number;
  confidence: CostConfidence;
}

export interface StageCostEstimate extends CostEstimate {
  stage: string;
  reserved_credits: number;
}

export interface AssetRegenCostEstimate extends CostEstimate {
  asset_type: "character" | "location" | "prop";
  asset_id: string;
  state_id: string | null;
  instruction_estimate?: CostEstimate;
}

export interface CreditTransaction {
  id: string;
  amount_credits: number;
  status: "reserved" | "settled" | "released";
  stage: string | null;
  description: string | null;
  project_id: string | null;
  job_id?: string | null;
  created_at: string;
  provider?: string | null;
  model?: string | null;
  provider_model?: string | null;
  operation?: string | null;
  input_tokens?: number;
  output_tokens?: number;
  image_count?: number;
  cost_usd?: number | null;
}

export interface CreditLedgerRun {
  run_id: string;
  job_id: string | null;
  stage: string | null;
  project_id: string | null;
  started_at: string;
  last_activity_at: string;
  estimate_credits: number;
  actual_credits: number;
  returned_credits: number;
  credits_added: number;
  status: "in_flight" | "complete" | "failed";
  rows: CreditTransaction[];
}

export interface CreditHistoryPage {
  runs: CreditLedgerRun[];
  limit: number;
  offset: number;
  has_more: boolean;
  month_used_credits: number;
}

export interface CreditPackage {
  id: string;
  label: string;
  price_cents: number;
  credits: number;
}

export interface PricingReference {
  notes: string[];
}

export interface PipelineEvent {
  type: string;
  stage?: string;
  total?: number;
  done?: number;
  message?: string;
  level?: "info" | "warn" | "error" | "dim" | "bold";
  error_code?: string;
  balance_credits?: number;
  required_credits?: number;
  shortfall_credits?: number;
  // Sub-item streaming activity (stage_activity)
  fraction?: number | null;
  detail?: string | null;
  at?: string;
  // Per-page events (draw stage)
  page_number?: number;
  revision?: number;
  started_at?: string;
  status?: "ok" | "failed";
  duration_ms?: number;
  error?: string | null;
}

export type GenerationJobStatus = "queued" | "running" | "complete" | "failed";

export interface GenerationJob {
  id: string;
  project_name: string;
  kind: string;
  label: string;
  payload: Record<string, unknown>;
  status: GenerationJobStatus;
  queue_position: number | null;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  classification?: string | null;
  user_message?: string | null;
  recoverable?: boolean | null;
}

export const STAGE_ORDER: StageName[] = [
  "extract",
  "brief",
  "style",
  "cast",
  "adapt",
  "plan",
  "draw",
  "finish",
];

export const STAGE_DISPLAY_NAMES: Record<StageName, string> = {
  extract: "EXTRACT",
  brief: "BRIEF",
  style: "LOOK & FEEL",
  cast: "CAST",
  adapt: "ADAPT",
  plan: "PLAN",
  draw: "DRAW",
  finish: "FINISH",
};

export const STAGE_ROUTES: Record<StageName, string> = {
  extract: "extract",
  brief: "story",
  style: "styles",
  cast: "cast",
  adapt: "adapt",
  plan: "plan",
  draw: "pages",
  finish: "book",
};

export const ROUTE_TO_STAGE: Record<string, StageName> = Object.fromEntries(
  Object.entries(STAGE_ROUTES).map(([k, v]) => [v, k as StageName]),
);

// ── Stage data types ──────────────────────────────────────────────────────────

export interface CharacterRelationship {
  character_id: string;
  relationship: string;
}

/** One distinct look an entity takes on mid-story (e.g. silver hands). When
 * visually_significant, the cast stage generates its own ref under
 * refs/<id>/states/<state_id>/ (characters) or plates/<state_id>.png (locations). */
export interface AppearanceState {
  id: string;
  label: string;
  visual_anchor: string;
  baseline_affect: string | null;
  visually_significant: boolean;
}

export interface Character {
  id: string;
  name: string;
  visual_anchor: string;
  age_range: string;
  gender: string;
  distinguishing_features: string[];
  baseline_affect: string | null;
  default_outfit: string;
  relationships: CharacterRelationship[];
  first_appearance_scene: string;
  appearance_states: AppearanceState[];
}

export interface Location {
  id: string;
  name: string;
  visual_anchor: string;
  time_of_day: string | null;
  mood: string;
  appearance_states: AppearanceState[];
}

export interface Scene {
  id: string;
  chapter: number;
  title: string;
  location_id: string;
  character_ids: string[];
  summary: string;
  scene_type: string;
  narrative_beat: string;
  source_start_quote: string;
}

export interface NarrativeArc {
  act: number;
  title: string;
  scenes: string[];
  turning_point: string | null;
}

export interface Prop {
  id: string;
  name: string;
  visual_anchor: string;
  first_appearance_scene: string | null;
}

export interface StoryBible {
  title: string;
  author: string;
  total_scenes: number;
  characters: Character[];
  locations: Location[];
  scenes: Scene[];
  narrative_arcs: NarrativeArc[];
  style_notes: string | null;
  props: Prop[];
}

export interface AdaptationBrief {
  revision: number;
  content_sha256: string;
  status: "draft" | "approved";
  story_promises: string[];
  themes: string[];
  point_of_view: string;
  narrator_treatment: string;
  tone: string;
  ambiguities: string[];
  motifs: string[];
  protected_language: string[];
  essential_events: string[];
  character_turns: string[];
  transformation_level: "faithful" | "medium_specific" | "transformative";
  desired_emphasis: string[];
  target_page_min: number;
  target_page_max: number;
}

export interface StoryDecision {
  story_bible: StoryBible;
  brief: AdaptationBrief | null;
}

export interface InstructedRefRegenResponse {
  status: string;
  instruction_status: "accepted";
  patch_summary: string;
  addendum: string;
  job: GenerationJob;
  char_id: string;
}

export interface InstructedPlateRegenResponse {
  status: string;
  instruction_status: "accepted";
  patch_summary: string;
  addendum: string;
  job: GenerationJob;
  loc_id: string;
}

export interface InstructedPropRegenResponse {
  status: string;
  instruction_status: "accepted";
  patch_summary: string;
  addendum: string;
  job: GenerationJob;
  prop_id: string;
}

export interface EditorialIssue {
  id: string;
  owner_stage: StageName;
  code: string;
  message: string;
  source_unit_ids?: string[];
  artifact_ids?: string[];
  evidence: string[];
  kind?: "editorial_issue";
  blocking?: false;
}

export interface LetteringItem {
  id: string;
  kind: "dialogue" | "thought" | "caption" | "sfx";
  text: string;
  speaker?: string | null;
  source_unit_ids?: string[];
}

export interface PageContent {
  id: string;
  order: number;
  beat_ids: string[];
  panel_role:
    | "establishing"
    | "standard"
    | "detail"
    | "reaction"
    | "action"
    | "transition"
    | "splash"
    | "inset";
  visual_intent: string;
  lettering: LetteringItem[];
  entity_ids: string[];
  appearance_state_ids: string[];
}

export interface ComicPage {
  page_number: number;
  revision: number;
  content_sha256: string;
  page_turn_role: "none" | "setup" | "reveal" | "cliffhanger" | "release" | "transition";
  spread_role: "single" | "left" | "right" | "spread";
  emphasis: "establisher" | "initial" | "prolongation" | "peak" | "release" | "transition";
  density_intent: "sparse" | "standard" | "dense";
  rhythm_intent: string;
  layout_intent: string;
  content: PageContent[];
  reading_order: string[];
}

export interface PageRenderRevision {
  page_number: number;
  revision: number;
  parent_revision: number | null;
  comic_page_revision: number;
  image_sha256: string;
  width: number;
  height: number;
}

export interface PageGenerationProvenance {
  render: PageRenderRevision;
}

export interface PageIssue {
  id: string;
  issue_type: string;
  classification: "invariant_failure" | "editorial_issue";
  correction_kind: "render_fidelity" | "copy_change";
  correction_owner: "adapt" | "draw";
  page_number: number;
  render_revision: number;
  evidence: string[];
  requested_correction: string;
  detected_region_ids?: string[];
  lettering_item_ids?: string[];
  status: "open" | "accepted" | "resolved" | "dismissed";
  resolution_revision: number | null;
  dismissal_reason?: string | null;
}

export interface PageIssueSummary {
  unresolved_issue_ids: string[];
  blocking_issue_ids: string[];
  accepted_editorial_issue_ids: string[];
}

export interface CompletePageSummary {
  page: ComicPage;
  active_render: PageGenerationProvenance | null;
  issues: PageIssue[];
  failure: PageGenerationFailure | null;
}

export interface PageGenerationFailure {
  page_number: number;
  request_sha256: string;
  failed_at: string;
  phase: "generation" | "analysis";
  classification: string;
  recoverable: boolean;
  user_message: string;
  error: string;
}

export interface CompletePagesResponse {
  pages: CompletePageSummary[];
  issue_summary: PageIssueSummary;
}

export interface CompletePageDetail {
  page: ComicPage;
  renders: PageGenerationProvenance[];
  analyses: RenderAnalysis[];
  issues: PageIssue[];
  failure: PageGenerationFailure | null;
}

export interface RenderAnalysis {
  page_number: number;
  render_revision: number;
  recognized_lettering: Record<string, string>;
  invariant_failures: Array<{ id: string; code: string; message: string; evidence: string[] }>;
  evidence: string[];
}

export interface InvariantFailure {
  id: string;
  owner_stage: StageName;
  code: string;
  message: string;
  source_unit_ids?: string[];
  artifact_ids?: string[];
  evidence: string[];
  kind?: "invariant_failure";
  blocking?: true;
}

export interface StageValidation {
  owner_stage: StageName;
  attempts: number;
  invariant_failures: InvariantFailure[];
  editorial_issues: EditorialIssue[];
  recommendations: string[];
}

export interface BookAdaptation {
  revision: number;
  editorial_issues: EditorialIssue[];
  treatment?: {
    causal_spine?: string[];
    character_arcs?: string[];
    reveals?: string[];
    consequences?: string[];
    aftermath?: string[];
    relative_emphasis?: string[];
  };
  beats?: Array<{
    id: string;
    order: number;
    summary: string;
    narrative_function?: string;
    story_functions?: string[];
    source_unit_ids?: string[];
    lettering?: Array<{ id: string; kind?: string; text?: string }>;
    transitions?: Array<{ description?: string }>;
    appearance_changes?: Array<{ description?: string }>;
  }>;
  ledger?: Array<{
    source_unit_id: string;
    disposition: string;
    adapted_beat_ids?: string[];
    reason?: string | null;
    preserved_function?: string;
  }>;
}

export interface BookPlan {
  revision: number;
  target_page_min: number;
  target_page_max: number;
  editorial_issues: EditorialIssue[];
  rhythm_summary?: string;
  pages?: Array<{ page_number: number; revision: number; content_sha256: string }>;
}

export interface FinishPreflight {
  edition_revision: number;
  validator_version?: number;
  pages: Array<{
    page_number: number;
    comic_page_revision: number;
    render_revision: number;
    invariant_failures: InvariantFailure[];
    diagnostics?: Array<{
      id: string;
      owner_stage: StageName;
      code: string;
      message: string;
      evidence: string[];
    }>;
    unresolved_editorial_issue_ids: string[];
    accepted_editorial_issue_ids: string[];
  }>;
  correction_requests: Array<{
    id: string;
    page_number: number;
    failure_codes: string[];
    requested_correction: string;
  }>;
  packages: Array<{ format: "pdf" | "cbz"; relative_path: string; byte_size: number }>;
  packaging_failures: InvariantFailure[];
}

export interface ImageGenerationMeta {
  version: number;
  kind: string;
  asset_identity?: string;
  prompt: string;
  prompt_sha256: string;
  parameters: Record<string, unknown>;
  failed_at?: string;
  classification?: "provider_blocked" | "generation_error" | string;
  recoverable?: boolean;
  user_message?: string;
  recovery?: Record<string, unknown>;
  provenance?: {
    request_id?: string;
    compiled_request_sha256?: string;
    execution_fingerprint?: string;
    effective_dimensions?: { width: number; height: number };
    actual_provider_model?: string | null;
    [key: string]: unknown;
  };
  error?: {
    type?: string;
    message?: string;
    chain?: Array<Record<string, unknown>>;
  };
}

export interface AssetVersion {
  version: number;
  current?: boolean;
  image_path: string;
  archived_at?: string;
  reason?: string;
  width?: number;
  height?: number;
  meta_path?: string;
}

export interface CharacterRefVersionsResponse {
  char_id: string;
  state_id: string | null;
  has_history: boolean;
  versions: AssetVersion[];
}

/**
 * A story from the short-story library catalog (libraryofshortstories.com,
 * proxied via GET /projects/short-stories). Only `code`, `title`, `author`,
 * `words`, and `genres` are guaranteed present across the catalog; everything
 * else is sparse. `code` — not `_id`, which exists on only a handful of
 * curated entries — is the stable unique handle and the import identifier.
 */
export interface ShortStory {
  code: string;
  title: string;
  author: string;
  words: number;
  genres: string[];
  publish_year?: number;
  publish_source?: string;
  rating?: number;
  series?: string;
  _id?: string;
  image?: string;
  blurb?: string;
  description?: string;
}

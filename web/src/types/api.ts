import type { LanguageCode } from "../locales/languages";
import type { LetteringElement } from "@lettering-engine";
import type { ModelFunding } from "../modelFunding";
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
  lettering_mode?: "integrated" | "editable";
  dev_model_selections?: Record<string, string>;
  style_template?: string;
  target_language?: LanguageCode;
  dev_mode?: boolean;
  dev_image_scale?: number;
  dev_image_steps?: number;
  dev_image_concurrency?: number;
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

/** A Cast reference that stopped the stage, with its stored failure reason. */
export interface CastFailure {
  item_id: string;
  asset_type: "character" | "location" | "prop" | null;
  entity_id: string | null;
  state_id: string | null;
  label: string;
  classification: string | null;
  attempts: number | null;
  message: string;
  /** After a decline: wording in the sent request that likely tripped the provider's filter. */
  likely_triggers?: ContentTrigger[];
}

export interface ContentTrigger {
  phrase: string;
  category: "nudity" | "sexual" | "gore" | "violence";
  /** Where the phrase was: the entry's description, a card direction, or the style notes. */
  source: "description" | "direction" | "style" | "other";
  context: string;
}

export interface StageInfo {
  approval_blocker?: string | null;
  failures?: CastFailure[];
  status: StageStatus;
  items_done: number;
  items_total: number;
  items_failed: string[];
  approved: boolean | null;
  cost_credits: number;
  estimated_cost_credits: number;
  error: string | null;
  error_detail?: string | null;
  error_code: string | null;
  // Structured credit-failure detail. Set only for credit reservations.
  balance_credits: number | null;
  required_credits: number | null;
  shortfall_credits: number | null;
  started_at: string | null;
  finished_at: string | null;
  last_progress_at: string | null;
  stale: boolean;
  in_flight: InFlightPage[];
  /** Latest validated-progress view a running stage published. */
  snapshot?: StageSnapshot | null;
}

export type PlanProgressPhase =
  | "mapping"
  | "reviewing_map"
  | "laying_out"
  | "checking"
  | "repairing"
  | "reviewing"
  | "complete";

export type PlanBatchState = "queued" | "writing" | "done" | "needs_repair" | "repairing";

export interface PlanProgressPage {
  page: number;
  emphasis: string;
  turn: string;
  spread: string;
  density: string;
  beats: number;
  /** Null until the page's batch is laid out and checked. */
  panels: number | null;
  lettering: number;
}

export interface PlanProgressSnapshot {
  kind: "plan";
  phase: PlanProgressPhase;
  beats: number;
  lettering_total: number;
  target_pages: { min: number; max: number };
  /** The transport runs one request at a time; queued batches wait. */
  serial_transport: boolean;
  pages: PlanProgressPage[];
  batches: { first: number; last: number; state: PlanBatchState }[];
  pages_laid_out: number;
  panels: number;
  lettering_placed: number;
}

export type AdaptProgressPhase =
  | "treatment"
  | "drafting"
  | "checking"
  | "reviewing"
  | "repairing"
  | "complete";

export type AdaptSectionState =
  | "queued"
  | "structuring"
  | "staged"
  | "lettering"
  | "done"
  | "needs_repair"
  | "repairing";

export interface AdaptProgressSection {
  units: number;
  title: string | null;
  state: AdaptSectionState;
  /** Story functions per beat; null until the section's structure validates. */
  beats: string[][] | null;
  lettering: number | null;
  /** Beat positions within this section cited by the latest check. */
  flagged: number[];
}

export interface AdaptProgressSnapshot {
  kind: "adapt";
  phase: AdaptProgressPhase;
  serial_transport: boolean;
  source_units: number;
  treatment: { spine: number; reveals: number; turns: number; arcs: number } | null;
  sections: AdaptProgressSection[];
  sections_done: number;
  beats: number;
  lettering: number;
  rounds: { round: number; blocking: number; notes: number }[];
  max_rounds: number;
}

export type StageSnapshot = PlanProgressSnapshot | AdaptProgressSnapshot;

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
  /** The part whose cover the card shows. */
  cover_part_id?: string | null;
  incompatible?: boolean;
  incompatibility_reason?: string | null;
}

/** One part of a series: its own issue with its own text, Brief and pages. */
export interface PartSummary {
  id: string;
  ordinal: number;
  title: string;
  characters: number;
  /** From the book map while it still describes this part's text. */
  synopsis?: string | null;
  /** What this part does in the whole book's structure. */
  book_role?: string | null;
  created_at: string;
  origin: string;
  stages: Record<string, StageStatus>;
  page_count: number;
  has_cover: boolean;
  /** Only the newest part's text changes, and only until its Adapt starts. */
  text_editable: boolean;
  text_locked_reason: string | null;
  /** Advisory: an earlier part was re-adapted after this one. */
  earlier_part_changed: boolean;
}

export interface ProjectStatus {
  /** The part this status describes; page work belongs to it. */
  part_id?: string | null;
  parts?: PartSummary[];
  active_jobs?: GenerationJob[];
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
  /** Who pays: subscription-funded work costs no credits. */
  funding?: ModelFunding;
}

export interface StageCostEstimate extends CostEstimate {
  archived_page_count?: number;
  stage: string;
  reserved_credits: number;
}

export interface AssetRegenCostEstimate extends CostEstimate {
  reference_assets_supported?: boolean;
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
  created_at: string;
  image_count?: number;
  /** Customer-facing name of what this row paid for. */
  label: string;
  page_number: number | null;
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
  /** Names a targeted action (a regenerated reference, a style sample); null for stage runs. */
  action: string | null;
  page_number: number | null;
  rows: CreditTransaction[];
}

export interface CreditHistoryPage {
  runs: CreditLedgerRun[];
  limit: number;
  offset: number;
  has_more: boolean;
  month_used_credits: number;
  /** Final charges per stage across the whole scoped history, not just this page. */
  spend_by_stage: Record<string, number>;
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
  // Validated-progress view (stage_snapshot)
  snapshot?: StageSnapshot | null;
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
  // Temporary image previews. These never count as saved artwork or progress.
  target?: string;
  request_id?: string;
  preview_index?: number;
  preview_total?: number;
  image_url?: string;
  reset?: boolean;
  settled?: boolean;
}

export interface ImagePreview {
  request_id: string;
  preview_index: number;
  image_url: string;
  /** The job finished; these completed pixels await only the saved file. */
  settled?: boolean;
}

export type GenerationJobStatus = "queued" | "running" | "complete" | "failed" | "cancelled";

export interface GenerationJob {
  stage?: StageName;
  id: string;
  project_name: string;
  kind: string;
  label: string;
  payload: Record<string, unknown>;
  status: GenerationJobStatus;
  queue_position: number | null;
  /** Queued behind this account's running work in another project. */
  waiting_for_other_project?: boolean;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  error: string | null;
  classification?: string | null;
  user_message?: string | null;
  recoverable?: boolean | null;
  phase?: "generation" | "analysis" | "ambiguous_submission" | "outcome_unknown" | "cancelled" | null;
  is_current_page?: boolean;
  /** The selected style frozen when this Cast reference job was admitted. */
  reference_style_hash?: string;
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
 * refs/<id>/states/<state_id>/ (characters) or plates/<id>/states/<state_id>.png (locations). */
export interface AppearanceState {
  id: string;
  label: string;
  visual_anchor: string;
  baseline_affect: string | null;
  visually_significant: boolean;
  canonical_equivalent?: boolean;
  continuity_guard?: string | null;
}

/** Extracted from the source, or added by the author in the Story editor. */
export type EntityOrigin = "extracted" | "author";

export interface Character {
  id: string;
  name: string;
  visual_anchor: string;
  age_range: string;
  gender: string;
  stature?: string;
  distinguishing_features: string[];
  baseline_affect: string | null;
  default_outfit: string;
  relationships: CharacterRelationship[];
  first_appearance_scene: string;
  appearance_states: AppearanceState[];
  aliases?: string[];
  origin?: EntityOrigin;
  cast_required?: boolean;
  identity_kind?: "individual" | "interchangeable" | "group";
  /** Cast reference sheet layout; see reference_forms.py. */
  reference_form?: ReferenceForm;
}

export type ReferenceForm = "figure" | "form" | "formation";

export interface Location {
  id: string;
  name: string;
  visual_anchor: string;
  time_of_day: string | null;
  mood: string;
  appearance_states: AppearanceState[];
  aliases?: string[];
  origin?: EntityOrigin;
}

export interface Scene {
  id: string;
  /** The part whose text holds this scene. */
  part_id?: string;
  chapter: number;
  title: string;
  location_id: string | null;
  character_ids: string[];
  summary: string;
  scene_type: string;
  narrative_beat: string;
  source_start_quote: string;
}

/** A run of one part's scenes that pursues one goal and ends on a turn. */
export interface StorySequence {
  part_id: string;
  number: number;
  title: string;
  scenes: string[];
  turn: string | null;
}

export interface Prop {
  id: string;
  name: string;
  visual_anchor: string;
  first_appearance_scene: string | null;
  appearance_states?: AppearanceState[];
  aliases?: string[];
  origin?: EntityOrigin;
}

/** A name the author removed; later extraction won't recreate it. */
export interface ExcludedEntity {
  kind: "character" | "location" | "prop";
  name: string;
  aliases: string[];
  /** What the removal took out; present when restoring brings the entry back whole. */
  removed?: { entity: Record<string, unknown>; scene_ids: string[] } | null;
}

export interface StoryBible {
  cast_character_ids?: string[];
  /** Bumped by every author edit; edits carry the revision they read. */
  revision?: number;
  excluded_entities?: ExcludedEntity[];
  title: string;
  author: string;
  total_scenes: number;
  characters: Character[];
  locations: Location[];
  scenes: Scene[];
  sequences: StorySequence[];
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
  status: "queued";
  job: GenerationJob;
  char_id: string;
}

export interface InstructedPlateRegenResponse {
  status: "queued";
  job: GenerationJob;
  loc_id: string;
}

export interface InstructedPropRegenResponse {
  status: "queued";
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
  appearance_states: Record<string, string>;
  camera: PanelCamera | null;
  acting: CharacterActing[];
}

export interface PanelCamera {
  shot:
    | "extreme_close_up"
    | "close_up"
    | "medium_close_up"
    | "medium"
    | "medium_wide"
    | "wide"
    | "extreme_wide"
    | "insert";
  angle: "eye_level" | "low_angle" | "high_angle" | "overhead" | "worms_eye" | "dutch";
}

/** Per-panel performance; left/right are the reader's screen directions. */
export interface CharacterActing {
  entity_id: string;
  facing:
    | "toward_viewer"
    | "three_quarter_left"
    | "three_quarter_right"
    | "profile_left"
    | "profile_right"
    | "away_from_viewer";
  gaze: string;
  expression: string;
  gesture: string;
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
  comic_page_sha256: string;
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
  status: "open" | "revised" | "accepted" | "resolved" | "dismissed";
  resolution_revision: number | null;
  dismissal_reason?: string | null;
}

export interface PageIssueSummary {
  unresolved_issue_ids: string[];
  blocking_issue_ids: string[];
  accepted_editorial_issue_ids: string[];
}

export interface PageAnalysisRecovery {
  status: "undrawn" | "stale_render" | "checked" | "cached_evidence" | "requires_ocr";
  requires_paid_call: boolean;
}

export type PageRedrawReason = "image" | "description" | "continuity" | "removed";

/** A Story Bible entry or Cast reference that changed after a page was drawn from it. */
export interface PageRedrawChange {
  reference_id: string;
  entity_id: string;
  appearance_state_id: string | null;
  label: string;
  reasons: PageRedrawReason[];
}

/** Why a drawn page's active art no longer matches its inputs. */
export interface PageRedrawReasons {
  plan_changed: boolean;
  changed_references: PageRedrawChange[];
}

export interface CompletePageSummary {
  /** Set when the page's plan or a Cast reference it was drawn from changed. */
  redraw?: PageRedrawReasons | null;
  lettering_mode?: "hybrid" | "baked";
  lettering_revision?: number | null;
  lettering_placement_review_needed?: boolean;
  page: ComicPage;
  active_render: PageGenerationProvenance | null;
  issues: PageIssue[];
  failure: PageGenerationFailure | null;
  analysis_recovery: PageAnalysisRecovery;
  /** The active art has a saved visual review from its draw or a re-check. */
  visual_reviewed?: boolean;
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
  redraws?: Array<PageRedrawReasons & { page_number: number }>;
  pages: CompletePageSummary[];
  issue_summary: PageIssueSummary;
}

export interface CompletePageDetail {
  active_render_revision: number | null;
  page: ComicPage;
  renders: PageGenerationProvenance[];
  analyses: RenderAnalysis[];
  issues: PageIssue[];
  failure: PageGenerationFailure | null;
  analysis_recovery: PageAnalysisRecovery;
}

/** A run of one manuscript unit; lettering runs cite the canonical items they became. */
export interface PageSourceSegment {
  text: string;
  kind: "lettering" | "depicted" | null;
  lettering_item_ids: string[];
}

export interface PageSourcePassage {
  scene_title: string | null;
  units: { id: string; ordinal: number; segments: PageSourceSegment[] }[];
}

/** Normalized page box. */
export interface PageSourceBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

/**
 * Where canonical lettering sits on the art: the saved editable element, or
 * the text region a text check matched on integrated art. Depicted detail is
 * never located because the drawing model composes the page.
 */
export interface PageSourceLettering {
  id: string;
  text: string;
  element: LetteringElement | null;
  region: PageSourceBox | null;
}

export type PageSourceGeometry =
  | { source: "lettering_placement"; lettering_revision: number }
  | { source: "text_check"; render_revision: number };

export interface PageSourceView {
  page_number: number;
  page_revision: number;
  passages: PageSourcePassage[];
  lettering: PageSourceLettering[];
  geometry: PageSourceGeometry | null;
}

export interface RenderAnalysis {
  render_image_sha256?: string;
  ocr_observations?: Array<{ id: string; text: string }>;
  observed_regions?: Array<{ id: string; polygon: Array<[number, number]> }>;
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
    lettering_placement_review_needed?: boolean;
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

/** A licensed story shipped with Canary and available for local import. */
/** How a manuscript reads before creation, split exactly as creation will split it. */
export interface SourcePreview {
  characters: number;
  words: number;
  chapters: number;
  part_target_characters: number;
  parts: { title: string | null; characters: number; words: number }[];
}

export interface ShortStory {
  code: string;
  title: string;
  author: string;
  words: number;
  genres: string[];
  source_kind?: "curated" | "archive";
  publish_year?: number | null;
  publish_source?: string | null;
  rights_note?: string;
  description?: string;
  showcase_note?: string;
  content_note?: string;
  source_note?: string;
  license?: string;
  license_url?: string;
  source_url?: string;
  text_source_url?: string;
  attribution_url?: string;
  sha256?: string;
}

export interface CastAssetReference {
  asset_type: "character" | "location" | "prop";
  asset_id: string;
  state_id?: string;
}

/** An image the author uploaded for a Cast correction. */
export interface UploadedCastReference {
  upload_id: string;
}

export type CastReferenceInput = CastAssetReference | UploadedCastReference;

export interface CastReferenceUpload extends UploadedCastReference {
  label: string;
  image_path: string;
}

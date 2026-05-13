export type StageName =
  | "extract"
  | "style"
  | "cast"
  | "adapt"
  | "plan"
  | "storyboard"
  | "direct"
  | "draw"
  | "compose";

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
  screenplay_model?: string;
  panel_model?: string;
  prompt_model?: string;
  dev_image_scale?: number;
  dev_image_steps?: number;
  dev_image_concurrency?: number;
  fallback_image_model?: string;
  image_width?: number;
  image_height?: number;
  image_steps?: number;
  image_quality?: "auto" | "low" | "medium" | "high";
  flux_guidance_scale?: number;
  max_panels_per_scene?: number;
  max_panels_per_page?: number;
  comic_theme?: string;
}

export interface StageInfo {
  status: StageStatus;
  items_done: number;
  items_total: number;
  items_failed: string[];
  cost_credits: number;
  estimated_cost_credits: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  stale: boolean;
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

export interface RegenCostEstimate extends CostEstimate {
  scene_id: string;
  panel_number: number;
  reserved_credits: null;
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
  operation?: string | null;
  input_tokens?: number;
  output_tokens?: number;
  image_count?: number;
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
}

export const STAGE_ORDER: StageName[] = [
  "extract",
  "style",
  "cast",
  "adapt",
  "plan",
  "storyboard",
  "direct",
  "draw",
  "compose",
];

export const STAGE_DISPLAY_NAMES: Record<StageName, string> = {
  extract: "EXTRACT",
  style: "LOOK & FEEL",
  cast: "CAST",
  adapt: "ADAPT",
  plan: "PLAN",
  storyboard: "STORYBOARD",
  direct: "DIRECT",
  draw: "DRAW",
  compose: "COMPOSE",
};

export const STAGE_ROUTES: Record<StageName, string> = {
  extract: "extract",
  style: "styles",
  cast: "cast",
  adapt: "adapt",
  plan: "plan",
  storyboard: "storyboard",
  direct: "direct",
  draw: "draw",
  compose: "compose",
};

export const ROUTE_TO_STAGE: Record<string, StageName> = Object.fromEntries(
  Object.entries(STAGE_ROUTES).map(([k, v]) => [v, k as StageName]),
);

// ── Stage data types ──────────────────────────────────────────────────────────

export interface CharacterRelationship {
  character_id: string;
  relationship: string;
}

export interface Character {
  id: string;
  name: string;
  visual_anchor: string;
  age_range: string;
  gender: string;
  distinguishing_features: string[];
  default_outfit: string;
  relationships: CharacterRelationship[];
  first_appearance_scene: string;
}

export interface Location {
  id: string;
  name: string;
  visual_anchor: string;
  time_of_day: string | null;
  mood: string;
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

export interface DialogueLine {
  character_id: string | null;
  text: string;
  type: string;
  source_beat_id?: string | null;
  source_text?: string | null;
  narration_mode?: string | null;
  preferred_zone?: string | null;
}

export interface ScreenplayBeat {
  type: string;
  character_id: string | null;
  content: string;
  source_text?: string | null;
  direction: string | null;
  transition_type: string | null;
  narration_reason?: string | null;
}

export interface Screenplay {
  scene_id: string;
  location_id: string;
  characters: string[];
  beats: ScreenplayBeat[];
}

export interface PanelBreakdown {
  scene_id: string;
  panel_number: number;
  shot_type: string;
  camera_angle: string;
  characters_present: string[];
  character_actions: Record<string, string>;
  character_expressions: Record<string, string>;
  character_positions: Record<string, string>;
  background_description: string;
  lighting: string;
  mood: string;
  dialogue: DialogueLine[];
  sfx: string[];
  transition_type: string | null;
  transition_note: string | null;
}

export interface LayoutPlanBeatRef {
  beat_id: string;
  scene_id: string;
  beat_index: number;
  type: string;
  character_id: string | null;
  content: string;
  source_text?: string | null;
  direction: string | null;
  transition_type: string | null;
  narration_reason?: string | null;
  emphasis_hint?: string | null;
  shot_hint?: string | null;
  transition_significance?: string | null;
}

export interface NarrationDecision {
  beat_id: string;
  scene_id: string;
  beat_index: number;
  source_text: string;
  caption_text: string | null;
  candidate_reason: string | null;
  decision: "rendered" | "visualized" | "dropped";
  mode: "attached_caption" | "caption_panel" | null;
  panel_id: string | null;
  preferred_zone: "top" | "bottom" | "left" | "right" | "overlay_center" | "none";
  decision_reason: string;
  fallback_decision: boolean;
  caption_text_override: string | null;
}

export interface StageCreditBreakdown {
  estimate_credits: number;
  reserved_credits: number | null;
  confidence: CostConfidence;
}

export interface NarrationImpact {
  impact: "compose_only" | "plan_only" | "redraw_selected_panels" | "replan_scene";
  affected_stages: string[];
  affected_panels: string[];
  requires_confirmation: boolean;
  reason: string;
  estimated_credits?: number;
  reserved_credits?: number;
  stage_credits?: Record<string, StageCreditBreakdown>;
}

export interface PanelGeometry {
  panel_id: string;
  shape_intent: string;
  region: number[];
  polygon: number[][];
  aspect_ratio: number | null;
  bleed: boolean;
  z_index: number;
}

export interface PlannedPanel {
  panel_id: string;
  scene_id: string;
  panel_number: number;
  beat_ids: string[];
  importance: string;
  shape_intent: string;
  aspect_preference: number | null;
  aspect_range: number[];
  crop_policy: string;
  dialogue_load: number;
  caption_load: number;
  transition_in: string | null;
  transition_out: string | null;
  generation_mode: string;
  shot_type: string;
  camera_angle: string;
  characters_present: string[];
  character_actions: Record<string, string>;
  character_expressions: Record<string, string>;
  character_positions: Record<string, string>;
  background_description: string;
  lighting: string;
  mood: string;
  dialogue: DialogueLine[];
  sfx: PlannedSfx[];
  has_narration_caption?: boolean;
  narration_mode?: string | null;
  preferred_caption_zone?: string | null;
}

export interface PlannedSfx {
  text: string;
  kind: SfxKind;
  intensity: 1 | 2 | 3;
}

export interface PlannedPage {
  page_id: string;
  page_number: number;
  panel_ids: string[];
  panel_geometries: PanelGeometry[];
  scene_ids: string[];
  scene_boundary_mode: string;
  page_rhythm_role: string;
  spread_id: string | null;
  cross_scene_reason: string | null;
}

export interface LayoutPlan {
  schema_version: number;
  metadata: {
    planner_version: number;
    planning_mode: string;
    source_screenplay_hash: string;
    source_scene_ids: string[];
    max_panels_per_page: number;
  };
  beats: LayoutPlanBeatRef[];
  planned_panels: PlannedPanel[];
  planned_pages: PlannedPage[];
  narration_decisions: NarrationDecision[];
  warnings: string[];
  user_overrides: Record<string, unknown>;
  regeneration_impact: Record<string, string>;
}

export interface PromptSubject {
  character_id: string | null;
  name: string;
  identity: string;
  action: string;
  expression: string;
  position: string;
}

export interface ImagePrompt {
  prompt_version?: number;
  planned_panel_id?: string | null;
  scene_id: string;
  panel_number: number;
  generation_mode?: string | null;
  shape_intent?: string | null;
  crop_policy?: string | null;
  transition_in?: string | null;
  transition_out?: string | null;
  has_narration_caption?: boolean;
  narration_mode?: string | null;
  preferred_caption_zone?: string | null;
  full_prompt: string;
  distilled_prompt?: string | null;
  style?: string | null;
  composition?: string | null;
  setting?: string | null;
  lighting?: string | null;
  mood?: string | null;
  subjects?: PromptSubject[];
  props?: string[];
  constraints?: string | null;
  reference_image_paths: string[];
  width: number;
  height: number;
  steps: number;
  continuity_note?: string | null;
}

export interface InstructedPanelRegenResponse {
  status: string;
  instruction_status: "accepted";
  patch_summary: string;
  job: GenerationJob;
  scene_id: string;
  panel_number: number;
  planned_panel_id?: string | null;
  prompt: ImagePrompt;
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

export interface Bubble {
  id: string;
  type: "speech" | "thought" | "narration";
  text: string;
  speaker_id: string | null;
  speaker_name: string | null;
  source_beat_id?: string | null;
  source_text?: string | null;
  narration_mode?: string | null;
  preferred_zone?: string | null;
  side: "left" | "right" | "center";
  full_width: boolean | null;
  x: number | null;
  y: number | null;
  width: number | null;
  tail_x: number | null;
  tail_y: number | null;
  tail_direction: "auto" | "up" | "down";
  font_family: string | null;
  font_size: number | null;
  font_color: string | null;
  fill_color: string | null;
  border_color: string | null;
  border_width: number | null;
  border_radius: number | null;
}

export type SfxKind = "impact" | "mechanical" | "voice" | "ambient" | "environment";
export type SfxAnchor =
  | "auto"
  | "bottom-center"
  | "top-center"
  | "bottom-left"
  | "bottom-right"
  | "top-left"
  | "top-right";

export interface Sfx {
  text: string;
  kind: SfxKind;
  intensity: 1 | 2 | 3;
  anchor: SfxAnchor;
  x: number | null;
  y: number | null;
  rotation: number;
  font_size: number | null;
}

export interface PagePanel {
  id: string;
  planned_panel_id: string | null;
  image_path: string;
  scene_id: string;
  panel_number: number;
  importance: string | null;
  generation_mode: string | null;
  bubbles: Bubble[];
  sfx: Sfx[];
  image_offset_x: number | null;
  image_offset_y: number | null;
  grid_column: string | null;
  grid_row: string | null;
  x: number | null;
  y: number | null;
  width: number | null;
  height: number | null;
  clip_path: string | null;
  z_index: number | null;
  shape_intent: string | null;
}

export interface ComicPage {
  page_number: number;
  source_page_id: string | null;
  theme: string;
  layout: string;
  layout_mode: "grid" | "freeform";
  style_vars: Record<string, string>;
  panels: PagePanel[];
}

export interface PageSummary {
  page_number: number;
  panel_count: number;
  layout: string;
  theme: string;
}

export interface ScreenplaySummary {
  scene_id: string;
  title: string;
  beat_count: number;
}

export interface PanelSceneSummary {
  scene_id: string;
  panel_count: number;
}

export interface ImageStatus {
  scene_id: string;
  panel_number: number;
  planned_panel_id?: string | null;
  status: "done" | "failed" | "pending" | "queued" | "running" | "stale";
  image_available?: boolean;
  accepted?: boolean;
  version_count?: number;
  failure_classification?: "provider_blocked" | "generation_error" | string | null;
  failure_message?: string | null;
  failure_detail?: string | null;
}

export interface ImageGenerationMeta {
  version: number;
  kind: string;
  prompt: string;
  prompt_sha256: string;
  parameters: Record<string, unknown>;
  failed_at?: string;
  classification?: "provider_blocked" | "generation_error" | string;
  recoverable?: boolean;
  user_message?: string;
  recovery?: Record<string, unknown>;
  error?: {
    type?: string;
    message?: string;
    chain?: Array<Record<string, unknown>>;
  };
}

export interface PanelImageVersion {
  version: number;
  current: boolean;
  scene_id: string;
  panel_number: number;
  image_path: string;
  archived_at?: string;
  reason?: string;
  width?: number;
  height?: number;
  meta_path?: string;
  failure_meta_path?: string;
  restored_from_version?: number;
}

export interface PanelImageVersionsResponse {
  scene_id: string;
  panel_number: number;
  has_history: boolean;
  versions: PanelImageVersion[];
}

export interface RestorePanelImageVersionResponse {
  scene_id: string;
  panel_number: number;
  restored: PanelImageVersion;
  versions: PanelImageVersion[];
}

export type PromptWarningCode =
  | "missing_character_ref"
  | "thin_composition"
  | "thin_setting"
  | "text_in_prompt"
  | "missing_style"
  | "inconsistent_dimensions";

export interface PromptWarning {
  code: PromptWarningCode;
  label: string;
  detail: string;
  scene_id: string;
  panel_number: number;
}

export interface CharacterVoice {
  character_id: string;
  character_name: string;
  font_family?: string | null;
  font_size?: number | null;
  font_color?: string | null;
  fill_color?: string | null;
  border_color?: string | null;
  border_width?: number | null;
  border_radius?: number | null;
}

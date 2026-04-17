export type StageName =
  | "extract"
  | "index"
  | "screenplay"
  | "panels"
  | "prompts"
  | "generate"
  | "assemble";

export type StageStatus =
  | "pending"
  | "running"
  | "awaiting_review"
  | "complete"
  | "failed";

export interface ConfigOverrides {
  style_template?: string;
  image_model?: string;
  target_language?: "en" | "es" | "fr";
  dev_mode?: boolean;
  dev_image_scale?: number;
  dev_image_steps?: number;
  dev_image_concurrency?: number;
  image_width?: number;
  image_height?: number;
  image_steps?: number;
  max_panels_per_scene?: number;
  max_panels_per_page?: number;
  comic_theme?: string;
}

export interface StageInfo {
  status: StageStatus;
  items_done: number;
  items_total: number;
  items_failed: string[];
  cost_usd: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ProjectSummary {
  name: string;
  project_name: string;
  created_at: string;
  total_cost_usd: number;
  furthest_stage: string | null;
  is_running: boolean;
  has_cover: boolean;
  cover_job: GenerationJob | null;
}

export interface ProjectStatus {
  project_name: string;
  created_at: string;
  total_cost_usd: number;
  is_running: boolean;
  has_cover: boolean;
  stages: Record<string, StageInfo>;
}

export interface PipelineEvent {
  type: string;
  stage?: string;
  total?: number;
  done?: number;
  message?: string;
  level?: "info" | "warn" | "error" | "dim" | "bold";
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
  "index",
  "screenplay",
  "panels",
  "prompts",
  "generate",
  "assemble",
];

export const STAGE_DISPLAY_NAMES: Record<StageName, string> = {
  extract: "EXTRACT",
  index: "CAST",
  screenplay: "ADAPT",
  panels: "STORYBOARD",
  prompts: "DIRECT",
  generate: "DRAW",
  assemble: "COMPOSE",
};

export const STAGE_ROUTES: Record<StageName, string> = {
  extract: "extract",
  index: "cast",
  screenplay: "adapt",
  panels: "storyboard",
  prompts: "direct",
  generate: "draw",
  assemble: "compose",
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
}

export interface ScreenplayBeat {
  type: string;
  character_id: string | null;
  content: string;
  direction: string | null;
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
  sfx: string | null;
  transition_note: string | null;
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
  scene_id: string;
  panel_number: number;
  full_prompt: string;
  style?: string | null;
  composition?: string | null;
  setting?: string | null;
  lighting?: string | null;
  mood?: string | null;
  subjects?: PromptSubject[];
  props?: string[];
  constraints?: string | null;
  reference_image_paths: string[];
  negative_prompt: null;
  width: number;
  height: number;
  steps: number;
  guidance_scale: number;
}

export interface Bubble {
  id: string;
  type: "speech" | "thought" | "narration";
  text: string;
  speaker_id: string | null;
  speaker_name: string | null;
  side: "left" | "right" | "center";
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

export interface Sfx {
  text: string;
  x: number | null;
  y: number | null;
  rotation: number;
  font_size: number | null;
}

export interface PagePanel {
  id: string;
  image_path: string;
  scene_id: string;
  panel_number: number;
  bubbles: Bubble[];
  sfx: Sfx | null;
  grid_column: string | null;
  grid_row: string | null;
}

export interface ComicPage {
  page_number: number;
  theme: string;
  layout: string;
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
  status: "done" | "failed" | "pending";
}

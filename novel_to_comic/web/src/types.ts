/** Mirrors Python Pydantic models — keep in sync manually. */

export interface ProjectSummary {
  name: string;
  project_name: string;
  created_at: string;
  total_cost_usd: number;
  furthest_stage: string | null;
}

export interface StageState {
  status: "pending" | "running" | "awaiting_review" | "complete" | "failed";
  items_done: number;
  items_total: number;
  items_failed: string[];
  cost_usd: number;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface ProjectStatus {
  project_name: string;
  created_at: string;
  total_cost_usd: number;
  stages: Record<string, StageState>;
}

export const STAGE_NAMES = [
  "extract",
  "index",
  "screenplay",
  "panels",
  "prompts",
  "generate",
  "assemble",
] as const;

export const CHECKPOINT_STAGES = new Set(["extract", "index", "generate"]);

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
  panels: PagePanel[];
}

export interface PageSummary {
  page_number: number;
  panel_count: number;
  layout: string;
  theme: string;
}

export interface PipelineEvent {
  type:
    | "stage_begin"
    | "stage_progress"
    | "stage_complete"
    | "stage_fail"
    | "log"
    | "pipeline_done";
  stage?: string;
  done?: number;
  total?: number;
  message?: string;
  level?: string;
}

export interface ConfigData {
  [key: string]: string | number | boolean | null;
}

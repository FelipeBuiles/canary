export type FontName = "Comic Neue" | "EB Garamond" | "Bangers" | "Special Elite" | "M PLUS 1p" | "Fredoka" | "Orbitron" | "Bungee" | "Baloo 2" | "Exo 2" | "Shrikhand" | "Creepster";
export type BalloonShape = "box" | "round" | "balloon" | "ellipse" | "cloud" | "whisper" | "burst" | "wavy" | "electric" | "none";
export type RoleName = "caption" | "speech" | "thought" | "sfx";
export interface Point { x: number; y: number }
export interface Rect extends Point { width: number; height: number }
export interface RoleStyle {
  font: FontName; font_weight: 400 | 700; min_font_size: number; max_font_size: number; line_height: number;
  align: "left" | "center" | "right"; color: string; fill: string; stroke: string;
  stroke_width: number; padding: number; corner_radius: number;
  shape: BalloonShape;
  letter_spacing: number; text_stroke: string; text_stroke_width: number;
  /** "upper": classic all-caps lettering; canonical copy stays as written. */
  text_case: "as_written" | "upper";
  tail_width: number;
  /** Outer knockout outline: around the balloon, or the letters when shape is "none". */
  halo_color: string; halo_width: number;
  shadow: "none" | "drop" | "extrude"; shadow_color: string; shadow_x: number; shadow_y: number;
  /** Letters fade vertically from ``color`` to this. */
  gradient_color: string;
  warp: "none" | "arc" | "wave"; warp_amount: number;
  jitter: number; skew: number;
}
export interface LetteringStyle {
  revision: number; content_sha256: string; label: string; source_direction: string;
  roles: Record<RoleName, RoleStyle>;
}
export interface ResolvedLettering {
  engine_version: string; locale: string; text: string; lines: string[];
  font_size: number; line_height: number; height: number; overflow: boolean; warnings: string[];
  width?: number | null;
  line_metrics?: { x: number; baseline: number; width: number; ascent: number; descent: number; glyph_x?: number[] | null }[];
}
export interface LetteringElement {
  id: string; source_lettering_item_id: string | null; role: RoleName;
  text_by_locale: Record<string,string>; suggested_placement: Rect; placement: Rect;
  hidden: boolean; style_override: RoleStyle | null; tail_target: Point | null;
  suggested_tail_target: Point | null; rotation: number; scale: number; z_index: number;
  /** Sideways bow of the tail spine, -1..1. */
  tail_bend?: number;
  /** Earlier balloon this one joins into a single silhouette. */
  link_to?: string | null;
  tight_box: boolean; resolved: ResolvedLettering | null;
}
export interface PageLettering {
  revision: number; content_sha256: string; page_number: number; comic_page_sha256: string;
  style_sha256: string; locale: string; canvas_aspect_ratio: number; elements: LetteringElement[];
  reviewed_against_render_revision: number | null; reviewed_against_image_sha256: string | null;
}
export interface Measure {
  (text: string, font: FontName, size: number, spacing?: number, weight?: number, italic?: boolean): number;
  metrics?: (text: string, font: FontName, size: number, spacing?: number, weight?: number, italic?: boolean) => { width: number; ascent: number; descent: number };
}
export const ENGINE_VERSION: string;
export const FONT_FILES: Readonly<Record<FontName,string>>;
export function fontCSS(base?: string): string;
export function loadFonts(): Promise<void>;
export function canvasMeasure(): Measure;
export function balancedLines(text: string, width: number, measure: (text: string)=>number, locale?: string): {lines:string[];overflow:boolean};
export const ROLE_DEFAULTS: Readonly<Pick<RoleStyle, "text_case" | "tail_width" | "halo_color" | "halo_width" | "shadow" | "shadow_color" | "shadow_x" | "shadow_y" | "gradient_color" | "warp" | "warp_amount" | "jitter" | "skew">>;
/** The element's effective style, saveable as an override (no layout seed). */
export function styleFor(element: LetteringElement, style: LetteringStyle): RoleStyle;
export function roleFor(element: LetteringElement, style: LetteringStyle): RoleStyle;
export function textFor(element: LetteringElement, locale: string): string;
export function elementRect(element: LetteringElement): Rect;
export function transformedBounds(element: LetteringElement, aspect: number): Rect;
export function resolvePage(state: PageLettering, style: LetteringStyle, measure: Measure): PageLettering;
export function renderOverlay(state: PageLettering, style: LetteringStyle): string;

export function defaultTailTarget(rect: Rect): Point | null;

export interface PageReadHead extends Rect { id: string; entity_id: string | null }
export interface PageReadMark extends Rect { text: string }
export interface PlacementEvidence {
  /** Panels read from the art's gutters (free, always present). */
  panels: Rect[];
  /** null when this art has no page read yet. */
  heads: PageReadHead[] | null;
  stray_lettering: PageReadMark[];
  in_world_text: PageReadMark[];
  /** Onscreen speaker entity per source lettering item. */
  speakers: Record<string, string | null>;
}
export type PlacementCheckCode = "crosses_panel" | "covers_face" | "tail_missing" | "tail_misses_speaker" | "covers_in_world_text" | "stray_lettering";
export interface PlacementCheck {
  code: PlacementCheckCode; severity: "fix" | "consider"; element_id: string | null;
  mark: Rect; text?: string; fix: Partial<LetteringElement> | null;
}
export function placementChecks(state: PageLettering, evidence: PlacementEvidence): PlacementCheck[];
export function tailTowardHead(body: Rect, head: Rect): Point;
export function clearOfHeads(rect: Rect, obstacles: Rect[], bounds: Rect, vertical?: boolean): Point | null;

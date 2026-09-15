export type FontName = "Comic Neue" | "EB Garamond" | "Bangers" | "Special Elite" | "M PLUS 1p" | "Fredoka" | "Orbitron" | "Bungee";
export type RoleName = "caption" | "speech" | "thought" | "sfx";
export interface Point { x: number; y: number }
export interface Rect extends Point { width: number; height: number }
export interface RoleStyle {
  font: FontName; font_weight: 400 | 700; min_font_size: number; max_font_size: number; line_height: number;
  align: "left" | "center" | "right"; color: string; fill: string; stroke: string;
  stroke_width: number; padding: number; corner_radius: number;
  shape: "box" | "round" | "ellipse" | "cloud" | "none";
  letter_spacing: number; text_stroke: string; text_stroke_width: number;
}
export interface LetteringStyle {
  revision: number; content_sha256: string; label: string; source_direction: string;
  roles: Record<RoleName, RoleStyle>;
}
export interface ResolvedLettering {
  engine_version: string; locale: string; text: string; lines: string[];
  font_size: number; line_height: number; height: number; overflow: boolean; warnings: string[];
}
export interface LetteringElement {
  id: string; source_lettering_item_id: string | null; role: RoleName;
  text_by_locale: Record<string,string>; suggested_placement: Rect; placement: Rect;
  hidden: boolean; style_override: RoleStyle | null; tail_target: Point | null;
  suggested_tail_target: Point | null; rotation: number; scale: number; z_index: number;
  tight_box: boolean; resolved: ResolvedLettering | null;
}
export interface PageLettering {
  revision: number; content_sha256: string; page_number: number; comic_page_sha256: string;
  style_sha256: string; locale: string; canvas_aspect_ratio: number; elements: LetteringElement[];
  reviewed_against_render_revision: number | null; reviewed_against_image_sha256: string | null;
}
export type Measure = (text: string, font: FontName, size: number, spacing?: number, weight?: number) => number;
export const ENGINE_VERSION: string;
export const FONT_FILES: Readonly<Record<FontName,string>>;
export function fontCSS(base?: string): string;
export function loadFonts(): Promise<void>;
export function canvasMeasure(): Measure;
export function balancedLines(text: string, width: number, measure: (text: string)=>number, locale?: string): {lines:string[];overflow:boolean};
export function roleFor(element: LetteringElement, style: LetteringStyle): RoleStyle;
export function textFor(element: LetteringElement, locale: string): string;
export function elementRect(element: LetteringElement): Rect;
export function transformedBounds(element: LetteringElement, aspect: number): Rect;
export function resolvePage(state: PageLettering, style: LetteringStyle, measure: Measure): PageLettering;
export function renderOverlay(state: PageLettering, style: LetteringStyle): string;

import { apiFetch } from "./client";

export type LetteringKind = "caption" | "dialogue" | "thought" | "sfx";
export interface LetteringBox { x: number; y: number; width: number; height: number }
export interface LetteringRole {
  font: "ComicNeue-Bold" | "EBGaramond-SemiBold" | "Bangers-Regular" | "MPLUS1p-Bold" | "SpecialElite-Regular" | "Exo2-SemiBold" | "Creepster-Regular";
  min_size: number; max_size: number; line_height: number; padding: number;
  align: "left" | "center" | "right"; color: string; fill: string; outline: string;
  border: number; radius: number; letter_spacing: number; stroke: number;
}
export interface LetteringStyle {
  preset: "literary" | "noir" | "manga" | "vintage"; direction: string;
  caption: LetteringRole; dialogue: LetteringRole; thought: LetteringRole; sfx: LetteringRole;
}
export interface LetteringElement {
  id: string; source_lettering_item_id: string | null; kind: LetteringKind;
  copies: Record<string, string>; suggested_placement: LetteringBox; placement: LetteringBox;
  tail_target: { x: number; y: number } | null; style_override: LetteringRole | null;
  hidden: boolean; rotation: number; scale: number; z_index: number;
  resolved: { lines: string[]; widths: number[]; font_size: number; body_height: number; overflow: boolean; reason: string; signature: string };
}
export interface PageLettering {
  schema_version: 1; revision: number; content_sha256: string; page_number: number;
  comic_page_sha256: string; locale: string; style: LetteringStyle;
  elements: LetteringElement[]; reviewed_against_render_revision: number | null;
}
export interface EditableLettering {
  mode: "editable"; state: PageLettering; svg: string; aspect: number; render_revision: number;
  saved_sha256: string | null; saved_revision: number; canonical_copy: Record<string, string>;
  placement_needs_review: boolean;
}
export type LetteringResponse = EditableLettering | { mode: "baked"; message: string };
const base = (project: string, page: number) => `/projects/${encodeURIComponent(project)}/pages/${page}/lettering`;
export const getLettering = (project: string, page: number) => apiFetch<LetteringResponse>(base(project, page));
export const getLetteringPresets = (project: string) => apiFetch<Record<string, LetteringStyle>>(`/projects/${encodeURIComponent(project)}/lettering/presets`);
export function letteringBody(state: PageLettering, expected: string | null) {
  // The server recalculates content identity after edits; never send a stale hash.
  const { content_sha256: _hash, ...value } = state;
  void _hash;
  return JSON.stringify({ state: value, expected_sha256: expected });
}
export const previewLettering = (project: string, state: PageLettering, signal?: AbortSignal) => apiFetch<EditableLettering>(`${base(project, state.page_number)}/preview`, { method: "POST", body: letteringBody(state, null), signal });
export const saveLettering = (project: string, state: PageLettering, expected: string | null) => apiFetch<EditableLettering>(base(project, state.page_number), { method: "PUT", body: letteringBody(state, expected) });
export const applyBookLetteringStyle = (project: string, style: LetteringStyle, expected_pages: Record<number, string | null>) => apiFetch<{ updated_pages: number[] }>(`/projects/${encodeURIComponent(project)}/lettering/style`, { method: "PUT", body: JSON.stringify({ style, expected_pages }) });

export const resetLettering = (project: string, page: number, expected_sha256: string | null) => apiFetch<EditableLettering>(`${base(project, page)}/reset`, { method: "POST", body: JSON.stringify({ expected_sha256 }) });

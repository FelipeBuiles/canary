import { apiFetch } from "./client";
import { seriesPath } from "./projectScope";
import type { PartSummary } from "../types/api";

/** A part's identity and the text it was created with. */
export interface PartRecord {
  id: string;
  ordinal: number;
  title: string;
  characters: number;
  created_at: string;
  origin: string;
  text_sha256: string;
}

/** A chapter heading found in a part's text; its start is a possible split. */
export interface DetectedChapter {
  index: number;
  title: string;
  start_offset: number;
  end_offset: number;
  characters: number;
  /** First-span source before its heading; it remains in this chapter's text. */
  opening_characters?: number;
}

export type PageFlagReason = "description" | "continuity" | "reference image" | "removed";

/** A drawn page whose artwork predates an edit to something on it. */
export interface PageFlag {
  page_number: number;
  render_revision: number;
  changes: {
    entity_id: string;
    appearance_state_id: string | null;
    label: string;
    reasons: PageFlagReason[];
  }[];
}

export interface PartTextInput {
  title?: string;
  text?: string;
  file?: File | null;
  autoSplit?: boolean;
}

export function hasPartText(value: PartTextInput): boolean {
  return !!value.file || !!value.text?.trim();
}

export interface PartTextResponse {
  part: PartRecord;
  chapters: DetectedChapter[];
  parts: PartSummary[];
}

export interface PartAddedResponse extends PartTextResponse {
  created: string[];
}

const partPath = (project: string, part: string) => `${seriesPath(project)}/parts/${encodeURIComponent(part)}`;

function textForm({ title, text, file, autoSplit }: PartTextInput): FormData {
  const form = new FormData();
  if (title?.trim()) form.append("title", title.trim());
  if (file) form.append("file", file);
  else if (text) form.append("text", text);
  if (autoSplit !== undefined) form.append("auto_split", String(autoSplit));
  return form;
}

export function listParts(project: string): Promise<{ parts: PartSummary[] }> {
  return apiFetch(`${seriesPath(project)}/parts`);
}

export function addPart(project: string, input: PartTextInput): Promise<PartAddedResponse> {
  return apiFetch(`${seriesPath(project)}/parts`, { method: "POST", headers: {}, body: textForm(input) });
}

export function replacePartText(project: string, part: string, input: PartTextInput): Promise<PartTextResponse> {
  return apiFetch(`${partPath(project, part)}/text`, { method: "PUT", headers: {}, body: textForm(input) });
}

export function getPartChapters(project: string, part: string): Promise<{ part_id: string; chapters: DetectedChapter[] }> {
  return apiFetch(`${partPath(project, part)}/chapters`);
}

export function splitPart(
  project: string, part: string, boundaries: number[], titles: (string | null)[],
): Promise<{ parts: PartSummary[]; created: string[] }> {
  return apiFetch(`${partPath(project, part)}/split`, {
    method: "POST",
    body: JSON.stringify({ boundaries, titles }),
  });
}

export function renamePart(project: string, part: string, title: string): Promise<{ part: PartRecord }> {
  return apiFetch(partPath(project, part), { method: "PATCH", body: JSON.stringify({ title }) });
}

export function deletePart(project: string, part: string): Promise<{ parts: PartSummary[] }> {
  return apiFetch(partPath(project, part), { method: "DELETE" });
}

export function getPageFlags(project: string, part: string): Promise<{ pages: PageFlag[] }> {
  return apiFetch(`${partPath(project, part)}/page-flags`);
}

export function exportParts(
  project: string, partIds: string[], format: "pdf" | "cbz",
): Promise<{ file: string; byte_size: number }> {
  return apiFetch(`${seriesPath(project)}/parts/export`, {
    method: "POST",
    body: JSON.stringify({ part_ids: partIds, format }),
  });
}

export function combinedExportUrl(project: string, file: string): string {
  return `/api${seriesPath(project)}/parts/export/${encodeURIComponent(file)}`;
}

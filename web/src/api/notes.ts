import { apiFetch } from "./client";
import { projectPath } from "./projectScope";
import type { CostEstimate } from "../types/api";

/** What a change reaches beyond the page's art, as the change check named it. */
export type NoteClaim =
  | { kind: "line"; lettering_item_id: string; text: string | null; speaker_entity_id: string | null }
  | {
    kind: "look"; entity_id: string; fact: string; start_page: number; end_page: number | null;
    state_id: string | null; look_label: string | null; look_anchor: string | null;
  }
  | { kind: "beat"; beat_ids: string[]; note: string };

export interface ScopedPage {
  page_number: number;
  panels: number[];
  drawn: boolean;
  reason: "line" | "beat" | "look";
}

export interface FactCheck {
  page_number: number;
  render_revision: number;
  breaks_fact: boolean;
  panels: number[];
  evidence: string;
}

/** One note carried beyond its page: what it touches, what was checked, what changed. */
export interface NoteChange {
  id: string;
  page_number: number;
  note: string;
  claim: NoteClaim;
  scope: { pages: ScopedPage[]; beat_ids: string[]; end_page: number | null; from_state_id: string | null };
  status: "proposed" | "applied" | "undone";
  checks: FactCheck[];
  pages: number[];
  state_id: string | null;
  added_state: boolean;
  redraw_pages: number[];
  check_pages: number[];
  default_pages: number[];
}

export type NoteChecksEstimate = CostEstimate & { pages: number[] };
export type NoteApplyEstimate = CostEstimate & { pages: number[] };

/** List every page the note touches. Free; nothing changes. */
export function previewNote(project: string, pageNumber: number, note: string, claim: NoteClaim): Promise<NoteChange> {
  return apiFetch(`${projectPath(project)}/notes/preview`, {
    method: "POST",
    body: JSON.stringify({ page_number: pageNumber, note, claim }),
  });
}

export function getNoteChecksEstimate(project: string, changeId: string): Promise<NoteChecksEstimate> {
  return apiFetch(`${projectPath(project)}/notes/${changeId}/checks/estimate`);
}

/** Look at each other drawn page in the run for art that breaks the fact. */
export function checkNotePages(project: string, changeId: string): Promise<NoteChange> {
  return apiFetch(`${projectPath(project)}/notes/${changeId}/checks`, { paidAction: true, method: "POST" });
}

export function getNoteApplyEstimate(project: string, changeId: string): Promise<NoteApplyEstimate> {
  return apiFetch(`${projectPath(project)}/notes/${changeId}/estimate`);
}

/** Change the Story Bible, script and page plan together, or nothing. */
export function applyNote(project: string, changeId: string, pages: number[]): Promise<NoteChange> {
  return apiFetch(`${projectPath(project)}/notes/${changeId}/apply`, {
    paidAction: true, method: "POST",
    body: JSON.stringify({ pages }),
  });
}

/** Put the script and page plan back; drawn art stays in each page's history. */
export function undoNote(project: string, changeId: string): Promise<NoteChange> {
  return apiFetch(`${projectPath(project)}/notes/${changeId}/undo`, { method: "POST" });
}

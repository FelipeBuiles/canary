import { apiFetch } from "./client";
import type { LetteringStyle, PageLettering, PageReadHead, PageReadMark, Point, Rect } from "@lettering-engine";
import type { CostEstimate, GenerationJob } from "../types/api";
export type { LetteringStyle, PageLettering, LetteringElement, RoleStyle, RoleName, Rect, Point } from "@lettering-engine";
export interface HybridLetteringResponse {
  mode: "hybrid";
  state: PageLettering;
  style: LetteringStyle;
  saved_revision: number;
  render_revision: number;
  render_image_sha256: string;
  source_stale: boolean;
  needs_save: boolean;
  placement_review_needed: boolean;
  canonical: Record<string, {
    text: string;
    kind: string;
    speaker: string | null;
    delivery: string;
    panel_number: number;
  }>;
  evidence: LetteringEvidence;
}
/** Free placement evidence for the current art; hints only, never placement review. */
export interface LetteringEvidence {
  panels: Rect[];
  speakers: Record<string, string | null>;
  speaker_names: Record<string, string>;
  /** The stored text check for exactly this art, or null before one runs. */
  page_read: {
    render_revision: number;
    /** null: this check ran before it located faces. */
    heads: PageReadHead[] | null;
    stray_lettering: PageReadMark[];
    in_world_text: PageReadMark[];
  } | null;
}
export interface LetteringSuggestions {
  render_revision: number;
  render_image_sha256: string;
  uses_faces: boolean;
  elements: Record<string, { placement: Rect; tail_target: Point | null }>;
}
export type LetteringResponse = HybridLetteringResponse | {
  mode: "baked";
  message: string;
};
const root = (project: string) => `/projects/${encodeURIComponent(project)}`;
const path = (project: string, page: number) => `${root(project)}/pages/${page}/lettering`;
export const getPageLettering = (project: string, page: number) => apiFetch<LetteringResponse>(path(project, page));
export function putPageLettering(project: string, page: number, state: PageLettering, base: HybridLetteringResponse, markReviewed = false) {
  return apiFetch<HybridLetteringResponse>(path(project, page), {
    method: "PUT", body: JSON.stringify({
      state: { ...state, content_sha256: "" }, expected_revision: base.saved_revision,
      expected_image_sha256: base.render_image_sha256, expected_style_sha256: base.style.content_sha256,
      mark_reviewed: markReviewed,
    })
  });
}
export const resetPageLettering = (project: string, page: number, base: HybridLetteringResponse) => apiFetch<HybridLetteringResponse>(`${path(project, page)}/reset`, {
  method: "POST", body: JSON.stringify({
    expected_revision: base.saved_revision, expected_image_sha256: base.render_image_sha256,
  })
});
export const getLetteringSuggestions = (project: string, page: number) => apiFetch<LetteringSuggestions>(`${path(project, page)}/suggestions`);
export const getBookLetteringStyle = (project: string) => apiFetch<{
  style: LetteringStyle;
  presets: Record<string, LetteringStyle>;
}>(`${root(project)}/lettering/style`);
export const putBookLetteringStyle = (project: string, style: LetteringStyle, revision: number) => apiFetch<LetteringStyle>(`${root(project)}/lettering/style`, {
  method: "PUT", body: JSON.stringify({
    style: { ...style, content_sha256: "" }, expected_revision: revision,
  })
});
export function pageCompositePreviewUrl(project: string, page: number, revision: number, rendition: "reader" | "thumbnail" | "full", letteringRevision?: number | null) {
  return `/api${root(project)}/pages/${page}/composite/${rendition}?render_revision=${revision}&lettering=${letteringRevision ?? 0}`;
}

export type LetteringLocale = "en" | "es" | "fr";

export interface LetteringTranslationEstimate extends CostEstimate {
  funding: "api" | "codex_subscription";
  target_locale: LetteringLocale;
  snapshot_sha256: string;
  page_count: number;
  element_count: number;
  translate_count: number;
  preserved_target_count: number;
  /** The project's active lettering language; "source" is the original copy. */
  current_locale?: LetteringLocale | "source";
}

export interface LetteringTranslationRequest {
  target_locale: LetteringLocale;
  expected_snapshot_sha256: string;
}

export function getLetteringTranslationEstimate(project: string, targetLocale: LetteringLocale) {
  return apiFetch<LetteringTranslationEstimate>(`${root(project)}/lettering/translation-estimate?target_locale=${targetLocale}`);
}

export function translateProjectLettering(project: string, request: LetteringTranslationRequest) {
  return apiFetch<{ job: GenerationJob }>(`${root(project)}/lettering/translate`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

/** Free switch to a language every element already stores; 409 when any are missing. */
export function switchStoredLetteringLocale(project: string, request: LetteringTranslationRequest) {
  return apiFetch<{ locale: LetteringLocale; changed: boolean }>(`${root(project)}/lettering/locale`, {
    method: "POST",
    body: JSON.stringify(request),
  });
}

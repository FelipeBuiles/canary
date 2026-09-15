import { apiFetch } from "./client";
import type { LetteringStyle, PageLettering } from "@lettering-engine";
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

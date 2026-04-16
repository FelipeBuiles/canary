import { apiFetch } from "./client";
import type { ComicPage, PageSummary } from "../types/api";

export function listPages(project: string): Promise<PageSummary[]> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/`);
}

export function getPage(
  project: string,
  pageNum: number,
): Promise<ComicPage> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/${pageNum}`);
}

export function updatePage(
  project: string,
  pageNum: number,
  data: Partial<ComicPage>,
): Promise<ComicPage> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/${pageNum}`, {
    method: "PATCH",
    body: JSON.stringify(data),
  });
}

export function pagePreviewUrl(project: string, pageNum: number): string {
  return `/api/projects/${encodeURIComponent(project)}/pages/${pageNum}/preview`;
}

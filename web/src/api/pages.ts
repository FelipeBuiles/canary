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

export function replacePage(
  project: string,
  pageNum: number,
  data: ComicPage,
): Promise<ComicPage> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/${pageNum}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function reorderPanels(
  project: string,
  pages: { page_number: number; panel_ids: string[] }[],
): Promise<void> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/reorder`, {
    method: "POST",
    body: JSON.stringify({ pages }),
  });
}

export function triggerExport(
  project: string,
  format: "pdf" | "cbz",
): Promise<{ status: string; path: string }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/export/?format=${format}`, {
    method: "POST",
  });
}

export function downloadExportUrl(project: string, format: "pdf" | "cbz"): string {
  return `/api/projects/${encodeURIComponent(project)}/export/${format}`;
}

export function pagePreviewUrl(project: string, pageNum: number): string {
  return `/api/projects/${encodeURIComponent(project)}/pages/${pageNum}/preview`;
}

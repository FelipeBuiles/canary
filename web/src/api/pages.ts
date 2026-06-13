import { apiFetch } from "./client";
import type { ComicPage, PageSummary, LetteringStyle } from "../types/api";

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

export function getLetteringStyle(project: string): Promise<LetteringStyle> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/lettering-style`);
}

export function generateLetteringStyle(project: string, reroll = false): Promise<LetteringStyle> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/lettering-style/generate`, {
    method: "POST",
    body: JSON.stringify({ reroll }),
  });
}

export function setLetteringStyle(
  project: string,
  body: { mode: "auto" | "preset"; preset?: string },
): Promise<LetteringStyle> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/lettering-style`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function translatePageBubbles(
  project: string,
  targetLanguage?: "en" | "es" | "fr",
): Promise<{ status: string; target_language: string; updated: number; pages: PageSummary[] }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/translate-bubbles`, {
    method: "POST",
    body: JSON.stringify(targetLanguage ? { target_language: targetLanguage } : {}),
  });
}

export function translateSinglePageBubbles(
  project: string,
  pageNum: number,
  targetLanguage?: "en" | "es" | "fr",
): Promise<{ status: string; target_language: string; updated: number; page: ComicPage }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/${pageNum}/translate-bubbles`, {
    method: "POST",
    body: JSON.stringify(targetLanguage ? { target_language: targetLanguage } : {}),
  });
}

export function triggerExport(
  project: string,
  format: "pdf" | "cbz",
): Promise<{ status: string; path: string; url: string | null }> {
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

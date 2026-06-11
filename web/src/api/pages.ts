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

export function generatePageStyleVars(
  project: string,
): Promise<{ status: string; style_vars: Record<string, string>; pages: PageSummary[] }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/style-vars/generate`, {
    method: "POST",
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

export function setTheme(
  project: string,
  theme: string,
): Promise<{ status: string; theme: string; updated: number }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/set-theme`, {
    method: "POST",
    body: JSON.stringify({ theme }),
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

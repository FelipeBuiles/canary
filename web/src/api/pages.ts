import { apiFetch } from "./client";
import type { ComicPage, PageSummary, CharacterVoice } from "../types/api";

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

export function reflowPages(
  project: string,
  panelsPerPage: number,
): Promise<PageSummary[]> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/reflow`, {
    method: "POST",
    body: JSON.stringify({ panels_per_page: panelsPerPage }),
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

export function applyBubblePreset(
  project: string,
  presetName: string,
): Promise<{ status: string; preset_name: string; updated_bubbles: number }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/apply-bubble-preset`, {
    method: "POST",
    body: JSON.stringify({ preset_name: presetName }),
  });
}

export function getBubblePresets(
  project: string,
): Promise<Record<string, Record<string, string>>> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/bubble-presets`);
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

export function getCharacterVoices(
  project: string,
): Promise<Record<string, CharacterVoice>> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/character-voices`);
}

export function putCharacterVoice(
  project: string,
  voice: CharacterVoice,
): Promise<CharacterVoice> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/character-voices/${encodeURIComponent(voice.character_id)}`, {
    method: "PUT",
    body: JSON.stringify(voice),
  });
}

export function deleteCharacterVoice(
  project: string,
  characterId: string,
): Promise<{ status: string }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/character-voices/${encodeURIComponent(characterId)}`, {
    method: "DELETE",
  });
}

export function reflowSinglePage(
  project: string,
  pageNum: number,
  layoutPreset: string,
): Promise<ComicPage> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/pages/${pageNum}/reflow`, {
    method: "POST",
    body: JSON.stringify({ layout_preset: layoutPreset }),
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

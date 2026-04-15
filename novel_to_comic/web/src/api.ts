/** Typed API client for the Canary dashboard. */

import type {
  ProjectSummary,
  ProjectStatus,
  PageSummary,
  ComicPage,
  ConfigData,
} from "./types";

const BASE = "/api";

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status}: ${text}`);
  }
  return res.json();
}

// ── Projects ────────────────────────────────────────────────────────────────

export function listProjects() {
  return json<ProjectSummary[]>(`${BASE}/projects/`);
}

export function getStatus(project: string) {
  return json<ProjectStatus>(`${BASE}/projects/${project}/status`);
}

// ── Pipeline ────────────────────────────────────────────────────────────────

export function runPipeline(project: string, stage?: string) {
  const url = stage
    ? `${BASE}/projects/${project}/run?stage=${stage}`
    : `${BASE}/projects/${project}/run`;
  return json<{ status: string; stage: string }>(url, { method: "POST" });
}

export function approveStage(project: string, stage: string) {
  return json<{ status: string; stage: string }>(
    `${BASE}/projects/${project}/approve/${stage}`,
    { method: "POST" }
  );
}

// ── Pages ───────────────────────────────────────────────────────────────────

export function listPages(project: string) {
  return json<PageSummary[]>(`${BASE}/projects/${project}/pages/`);
}

export function getPage(project: string, pageNum: number) {
  return json<ComicPage>(`${BASE}/projects/${project}/pages/${pageNum}`);
}

export function updatePage(project: string, pageNum: number, patch: object) {
  return json<ComicPage>(`${BASE}/projects/${project}/pages/${pageNum}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function pagePreviewUrl(project: string, pageNum: number) {
  return `${BASE}/projects/${project}/pages/${pageNum}/preview`;
}

export function pageThumbnailUrl(project: string, pageNum: number) {
  return `${BASE}/projects/${project}/files/assembly/pages/page_${String(pageNum).padStart(3, "0")}.png`;
}

// ── Export ───────────────────────────────────────────────────────────────────

export function triggerExport(project: string, format: "pdf" | "cbz" = "pdf") {
  return json<{ status: string; path: string }>(
    `${BASE}/projects/${project}/export/?format=${format}`,
    { method: "POST" }
  );
}

export function exportDownloadUrl(project: string, format: string) {
  return `${BASE}/projects/${project}/export/${format}`;
}

// ── Config ──────────────────────────────────────────────────────────────────

export function getConfig(project: string) {
  return json<ConfigData>(`${BASE}/projects/${project}/config/`);
}

export function updateConfig(project: string, patch: object) {
  return json<ConfigData>(`${BASE}/projects/${project}/config/`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

// ── SSE ─────────────────────────────────────────────────────────────────────

export function eventStreamUrl(project: string) {
  return `${BASE}/projects/${project}/events`;
}

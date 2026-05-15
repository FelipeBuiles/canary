import { create } from "zustand";
import type { InFlightPanel, StageInfo } from "../types/api";

export interface InFlightEntry {
  sceneId: string;
  panelNumber: number;
  startedAt: number; // ms epoch
}

export interface FinishRecord {
  sceneId: string;
  panelNumber: number;
  status: "ok" | "failed";
  durationMs: number;
  finishedAt: number; // ms epoch
  error?: string | null;
}

interface ProjectProgress {
  inFlight: Record<string, InFlightEntry>; // key = `${sceneId}-${panelNumber}`
  recentFinishes: FinishRecord[];          // newest first, capped
}

interface DrawProgressStore {
  byProject: Record<string, ProjectProgress>;

  hydrate: (project: string, stage: StageInfo | undefined) => void;
  applyPanelStart: (
    project: string,
    sceneId: string,
    panelNumber: number,
    startedAtIso: string,
  ) => void;
  applyPanelDone: (
    project: string,
    sceneId: string,
    panelNumber: number,
    status: "ok" | "failed",
    durationMs: number,
    error: string | null,
  ) => void;
  clear: (project: string) => void;
}

const FINISHES_CAP = 10;
const EMPTY_PROGRESS: ProjectProgress = { inFlight: {}, recentFinishes: [] };

function panelKey(sceneId: string, panelNumber: number): string {
  return `${sceneId}-${panelNumber}`;
}

function parseIso(iso: string): number {
  const t = Date.parse(iso);
  return Number.isNaN(t) ? Date.now() : t;
}

export const useDrawProgressStore = create<DrawProgressStore>((set) => ({
  byProject: {},

  hydrate: (project, stage) => {
    set((s) => {
      const inFlightArr: InFlightPanel[] = stage?.in_flight ?? [];
      const next: Record<string, InFlightEntry> = {};
      for (const p of inFlightArr) {
        next[panelKey(p.scene_id, p.panel_number)] = {
          sceneId: p.scene_id,
          panelNumber: p.panel_number,
          startedAt: parseIso(p.started_at),
        };
      }
      // Preserve any finishes already collected (SSE may have arrived before
      // the first /status response).
      const existing = s.byProject[project] ?? EMPTY_PROGRESS;
      return {
        byProject: {
          ...s.byProject,
          [project]: { inFlight: next, recentFinishes: existing.recentFinishes },
        },
      };
    });
  },

  applyPanelStart: (project, sceneId, panelNumber, startedAtIso) => {
    set((s) => {
      const existing = s.byProject[project] ?? EMPTY_PROGRESS;
      const k = panelKey(sceneId, panelNumber);
      if (existing.inFlight[k]) return s;
      return {
        byProject: {
          ...s.byProject,
          [project]: {
            ...existing,
            inFlight: {
              ...existing.inFlight,
              [k]: { sceneId, panelNumber, startedAt: parseIso(startedAtIso) },
            },
          },
        },
      };
    });
  },

  applyPanelDone: (project, sceneId, panelNumber, status, durationMs, error) => {
    set((s) => {
      const existing = s.byProject[project] ?? EMPTY_PROGRESS;
      const k = panelKey(sceneId, panelNumber);
      const nextInFlight = { ...existing.inFlight };
      delete nextInFlight[k];
      const finishedAt = Date.now();
      const finish: FinishRecord = {
        sceneId,
        panelNumber,
        status,
        durationMs,
        finishedAt,
        error,
      };
      const nextFinishes = [finish, ...existing.recentFinishes].slice(0, FINISHES_CAP);
      return {
        byProject: {
          ...s.byProject,
          [project]: { inFlight: nextInFlight, recentFinishes: nextFinishes },
        },
      };
    });
  },

  clear: (project) => {
    set((s) => {
      if (!s.byProject[project]) return s;
      const next = { ...s.byProject };
      delete next[project];
      return { byProject: next };
    });
  },
}));

// ── Selectors ────────────────────────────────────────────────────────────────

export function useInFlight(project: string): InFlightEntry[] {
  return useDrawProgressStore((s) => {
    const proj = s.byProject[project];
    if (!proj) return EMPTY_IN_FLIGHT;
    return Object.values(proj.inFlight).sort((a, b) => a.startedAt - b.startedAt);
  });
}

export function useRecentFinishes(project: string): FinishRecord[] {
  return useDrawProgressStore((s) => s.byProject[project]?.recentFinishes ?? EMPTY_FINISHES);
}

export function useInFlightSet(project: string): Set<string> {
  return useDrawProgressStore((s) => {
    const proj = s.byProject[project];
    if (!proj) return EMPTY_SET;
    return new Set(Object.keys(proj.inFlight));
  });
}

const EMPTY_IN_FLIGHT: InFlightEntry[] = [];
const EMPTY_FINISHES: FinishRecord[] = [];
const EMPTY_SET = new Set<string>();

// Throughput from a 60s sliding window of finishes (any status).
// Returns null when too few samples to be meaningful.
const THROUGHPUT_WINDOW_MS = 60_000;
const MIN_SAMPLES_FOR_THROUGHPUT = 3;

export function computeThroughputPerMin(finishes: FinishRecord[], now = Date.now()): number | null {
  const recent = finishes.filter((f) => now - f.finishedAt <= THROUGHPUT_WINDOW_MS);
  if (recent.length < MIN_SAMPLES_FOR_THROUGHPUT) return null;
  // Convert window count → per-minute rate. 60s window → already per-minute.
  return recent.length;
}

export function computeEtaSeconds(
  itemsRemaining: number,
  throughputPerMin: number | null,
): number | null {
  if (throughputPerMin == null || throughputPerMin <= 0) return null;
  if (itemsRemaining <= 0) return 0;
  return (itemsRemaining / throughputPerMin) * 60;
}

export function formatEta(seconds: number | null): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.round((seconds % 3600) / 60);
  return `${hours}h ${minutes}m`;
}

export function formatRelative(ms: number, now = Date.now()): string {
  const delta = Math.max(0, now - ms);
  const seconds = Math.round(delta / 1000);
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${Math.round(seconds / 3600)}h`;
}

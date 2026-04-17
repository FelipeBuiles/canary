import { create } from "zustand";
import type { GenerationJob, GenerationJobStatus } from "../types/api";

export interface ActiveRegen {
  key: string;
  jobId: string | null;
  status: Extract<GenerationJobStatus, "queued" | "running">;
  queuePosition: number | null;
}

interface RegenStore {
  active: Record<string, Record<string, ActiveRegen>>; // keyed by project name, then panel key
  bustTimestamps: Record<string, number>;         // keyed by "project/key"
  errors: Record<string, string>;                 // keyed by "project/key"

  begin: (project: string, key: string) => void;
  markStarted: (project: string, key: string) => void;
  attachJob: (project: string, key: string, job: GenerationJob) => void;
  updateJob: (project: string, key: string, job: GenerationJob) => void;
  complete: (project: string, key: string) => void;
  fail: (project: string, key: string, error: string) => void;
  clearError: (project: string, key: string) => void;
}

const EMPTY_ACTIVE_REGENS: Record<string, ActiveRegen> = {};

export const useRegenStore = create<RegenStore>((set) => ({
  active: {},
  bustTimestamps: {},
  errors: {},

  begin: (project, key) =>
    set((s) => {
      const errors = { ...s.errors };
      delete errors[`${project}/${key}`];
      return {
        active: {
          ...s.active,
          [project]: {
            ...(s.active[project] ?? {}),
            [key]: { key, jobId: null, status: "queued", queuePosition: null },
          },
        },
        errors,
      };
    }),

  markStarted: (project, key) =>
    set((s) => {
      const cur = s.active[project]?.[key];
      if (!cur || cur.status === "running") return s;
      return {
        active: {
          ...s.active,
          [project]: {
            ...(s.active[project] ?? {}),
            [key]: { ...cur, status: "running" },
          },
        },
      };
    }),

  attachJob: (project, key, job) =>
    set((s) => {
      const cur = s.active[project]?.[key];
      if (!cur) return s;
      const nextStatus = job.status === "running" ? "running" : "queued";
      if (
        cur.jobId === job.id &&
        cur.status === nextStatus &&
        cur.queuePosition === job.queue_position
      ) {
        return s;
      }
      return {
        active: {
          ...s.active,
          [project]: {
            ...(s.active[project] ?? {}),
            [key]: {
              ...cur,
              jobId: job.id,
              status: nextStatus,
              queuePosition: job.queue_position,
            },
          },
        },
      };
    }),

  updateJob: (project, key, job) =>
    set((s) => {
      const cur = s.active[project]?.[key];
      if (!cur) return s;
      if (job.status !== "queued" && job.status !== "running") return s;
      if (cur.status === job.status && cur.queuePosition === job.queue_position) return s;
      return {
        active: {
          ...s.active,
          [project]: {
            ...(s.active[project] ?? {}),
            [key]: {
              ...cur,
              status: job.status,
              queuePosition: job.queue_position,
            },
          },
        },
      };
    }),

  complete: (project, key) =>
    set((s) => {
      if (!s.active[project]?.[key]) return s;
      const projectActive = { ...(s.active[project] ?? {}) };
      delete projectActive[key];
      const active = { ...s.active };
      if (Object.keys(projectActive).length === 0) delete active[project];
      else active[project] = projectActive;
      return {
        active,
        bustTimestamps: { ...s.bustTimestamps, [`${project}/${key}`]: Date.now() },
      };
    }),

  fail: (project, key, error) =>
    set((s) => {
      if (!s.active[project]?.[key] && s.errors[`${project}/${key}`] === error) return s;
      const projectActive = { ...(s.active[project] ?? {}) };
      delete projectActive[key];
      const active = { ...s.active };
      if (Object.keys(projectActive).length === 0) delete active[project];
      else active[project] = projectActive;
      return {
        active,
        errors: { ...s.errors, [`${project}/${key}`]: error },
      };
    }),

  clearError: (project, key) =>
    set((s) => {
      const errors = { ...s.errors };
      delete errors[`${project}/${key}`];
      return { errors };
    }),
}));

export function useActiveRegens(project: string): Record<string, ActiveRegen> {
  return useRegenStore((s) => s.active[project] ?? EMPTY_ACTIVE_REGENS);
}

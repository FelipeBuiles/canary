import { create } from "zustand";
import type { GenerationJob, GenerationJobStatus } from "../types/api";

const EMPTY = new Set<number>();
const EMPTY_JOBS: Record<number, string> = {};
const EMPTY_STATUS: Record<number, Extract<GenerationJobStatus, "queued" | "running">> = {};
const EMPTY_QUEUE_POSITIONS: Record<number, number | null> = {};

interface StyleGenStore {
  /** Set of indices currently generating, keyed by project name */
  pending: Record<string, Set<number>>;
  jobIds: Record<string, Record<number, string>>;
  statuses: Record<string, Record<number, Extract<GenerationJobStatus, "queued" | "running">>>;
  queuePositions: Record<string, Record<number, number | null>>;

  add: (project: string, indices: number[]) => void;
  attachJobs: (project: string, jobs: GenerationJob[]) => void;
  updateJob: (project: string, job: GenerationJob) => void;
  remove: (project: string, indices: number[]) => void;
}

export const useStyleGenStore = create<StyleGenStore>((set) => ({
  pending: {},
  jobIds: {},
  statuses: {},
  queuePositions: {},

  add: (project, indices) =>
    set((s) => {
      const current = s.pending[project] ?? EMPTY;
      const next = new Set(current);
      for (const i of indices) next.add(i);
      const currentStatuses = s.statuses[project] ?? EMPTY_STATUS;
      const nextStatuses = { ...currentStatuses };
      const currentPositions = s.queuePositions[project] ?? EMPTY_QUEUE_POSITIONS;
      const nextPositions = { ...currentPositions };
      for (const i of indices) {
        nextStatuses[i] = "queued";
        nextPositions[i] = null;
      }
      return {
        pending: { ...s.pending, [project]: next },
        statuses: { ...s.statuses, [project]: nextStatuses },
        queuePositions: { ...s.queuePositions, [project]: nextPositions },
      };
    }),

  attachJobs: (project, jobs) =>
    set((s) => {
      const currentJobIds = s.jobIds[project] ?? EMPTY_JOBS;
      const currentStatuses = s.statuses[project] ?? EMPTY_STATUS;
      const currentPositions = s.queuePositions[project] ?? EMPTY_QUEUE_POSITIONS;
      const nextJobIds = { ...currentJobIds };
      const nextStatuses = { ...currentStatuses };
      const nextPositions = { ...currentPositions };
      for (const job of jobs) {
        const index = Number(job.payload.index);
        if (!Number.isFinite(index)) continue;
        nextJobIds[index] = job.id;
        if (job.status === "queued" || job.status === "running") {
          nextStatuses[index] = job.status;
          nextPositions[index] = job.queue_position;
        }
      }
      return {
        jobIds: { ...s.jobIds, [project]: nextJobIds },
        statuses: { ...s.statuses, [project]: nextStatuses },
        queuePositions: { ...s.queuePositions, [project]: nextPositions },
      };
    }),

  updateJob: (project, job) =>
    set((s) => {
      const index = Number(job.payload.index);
      if (!Number.isFinite(index) || (job.status !== "queued" && job.status !== "running")) {
        return {};
      }
      return {
        statuses: {
          ...s.statuses,
          [project]: {
            ...(s.statuses[project] ?? EMPTY_STATUS),
            [index]: job.status,
          },
        },
        queuePositions: {
          ...s.queuePositions,
          [project]: {
            ...(s.queuePositions[project] ?? EMPTY_QUEUE_POSITIONS),
            [index]: job.queue_position,
          },
        },
      };
    }),

  remove: (project, indices) =>
    set((s) => {
      const current = s.pending[project];
      if (!current) return {};
      const next = new Set(current);
      for (const i of indices) next.delete(i);
      const nextJobIds = { ...(s.jobIds[project] ?? EMPTY_JOBS) };
      const nextStatuses = { ...(s.statuses[project] ?? EMPTY_STATUS) };
      const nextPositions = { ...(s.queuePositions[project] ?? EMPTY_QUEUE_POSITIONS) };
      for (const i of indices) {
        delete nextJobIds[i];
        delete nextStatuses[i];
        delete nextPositions[i];
      }
      if (next.size === 0) {
        const { [project]: _, ...rest } = s.pending;
        const { [project]: _jobs, ...jobIds } = s.jobIds;
        const { [project]: _statuses, ...statuses } = s.statuses;
        const { [project]: _positions, ...queuePositions } = s.queuePositions;
        return { pending: rest, jobIds, statuses, queuePositions };
      }
      return {
        pending: { ...s.pending, [project]: next },
        jobIds: { ...s.jobIds, [project]: nextJobIds },
        statuses: { ...s.statuses, [project]: nextStatuses },
        queuePositions: { ...s.queuePositions, [project]: nextPositions },
      };
    }),
}));

/** Stable selector — returns EMPTY (same ref) when no pending set exists. */
export function usePendingIndices(project: string): Set<number> {
  return useStyleGenStore((s) => s.pending[project] ?? EMPTY);
}

export function useStyleJobIds(project: string): Record<number, string> {
  return useStyleGenStore((s) => s.jobIds[project] ?? EMPTY_JOBS);
}

export function useStyleJobStatuses(
  project: string,
): Record<number, Extract<GenerationJobStatus, "queued" | "running">> {
  return useStyleGenStore((s) => s.statuses[project] ?? EMPTY_STATUS);
}

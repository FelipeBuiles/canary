import { create } from "zustand";

interface ActiveRegen {
  key: string;
  startedAt: number | null;
}

interface RegenStore {
  active: Record<string, ActiveRegen | null>;    // keyed by project name
  bustTimestamps: Record<string, number>;         // keyed by "project/key"
  errors: Record<string, string>;                 // keyed by "project/key"

  begin: (project: string, key: string) => void;
  markStarted: (project: string) => void;
  complete: (project: string, key: string) => void;
  fail: (project: string, key: string, error: string) => void;
  clearError: (project: string, key: string) => void;
}

export const useRegenStore = create<RegenStore>((set) => ({
  active: {},
  bustTimestamps: {},
  errors: {},

  begin: (project, key) =>
    set((s) => {
      const errors = { ...s.errors };
      delete errors[`${project}/${key}`];
      return { active: { ...s.active, [project]: { key, startedAt: null } }, errors };
    }),

  markStarted: (project) =>
    set((s) => {
      const cur = s.active[project];
      if (!cur) return {};
      return { active: { ...s.active, [project]: { ...cur, startedAt: Date.now() } } };
    }),

  complete: (project, key) =>
    set((s) => ({
      active: { ...s.active, [project]: null },
      bustTimestamps: { ...s.bustTimestamps, [`${project}/${key}`]: Date.now() },
    })),

  fail: (project, key, error) =>
    set((s) => ({
      active: { ...s.active, [project]: null },
      errors: { ...s.errors, [`${project}/${key}`]: error },
    })),

  clearError: (project, key) =>
    set((s) => {
      const errors = { ...s.errors };
      delete errors[`${project}/${key}`];
      return { errors };
    }),
}));

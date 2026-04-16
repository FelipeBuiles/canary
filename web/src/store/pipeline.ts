import { create } from "zustand";
import type { PipelineEvent } from "../types/api";

interface PipelineStore {
  connected: boolean;
  events: PipelineEvent[];
  connect: (projectName: string) => void;
  disconnect: () => void;
  clearEvents: () => void;
}

let eventSource: EventSource | null = null;

export const usePipelineStore = create<PipelineStore>((set) => ({
  connected: false,
  events: [],

  connect: (projectName: string) => {
    usePipelineStore.getState().disconnect();
    const es = new EventSource(
      `/api/projects/${encodeURIComponent(projectName)}/events`,
    );
    es.onmessage = (e) => {
      try {
        const event: PipelineEvent = JSON.parse(e.data);
        set((state) => ({ events: [...state.events, event] }));
      } catch {
        // ignore malformed events
      }
    };
    es.onerror = () => {
      es.close();
      set({ connected: false });
    };
    es.onopen = () => set({ connected: true });
    eventSource = es;
  },

  disconnect: () => {
    eventSource?.close();
    eventSource = null;
    set({ connected: false });
  },

  clearEvents: () => set({ events: [] }),
}));

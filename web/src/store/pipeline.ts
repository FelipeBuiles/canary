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
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectDelay = 1000;

function clearReconnectTimer() {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }
}

function closeCurrentSource(es?: EventSource) {
  if (es && eventSource !== es) return;
  clearReconnectTimer();
  eventSource?.close();
  eventSource = null;
  reconnectDelay = 1000;
}

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
        if (event.type === "pipeline_done") {
          closeCurrentSource(es);
          set({ connected: false });
        }
      } catch {
        // ignore malformed events
      }
    };
    es.onerror = () => {
      if (eventSource !== es) return;
      es.close();
      set({ connected: false });

      // Reconnect with exponential backoff if disconnect() wasn't called
      if (eventSource !== null) {
        reconnectTimer = setTimeout(() => {
          reconnectDelay = Math.min(reconnectDelay * 2, 30_000);
          usePipelineStore.getState().connect(projectName);
        }, reconnectDelay);
      }
    };
    es.onopen = () => {
      reconnectDelay = 1000;
      set({ connected: true });
    };
    eventSource = es;
  },

  disconnect: () => {
    closeCurrentSource();
    set({ connected: false });
  },

  clearEvents: () => set({ events: [] }),
}));

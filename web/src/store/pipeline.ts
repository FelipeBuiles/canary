import { create } from "zustand";
import type { PipelineEvent } from "../types/api";
import { useInsufficientCreditsStore } from "./insufficientCredits";
import { STAGE_DISPLAY_NAMES, type StageName } from "../types/api";

interface PipelineStore {
  connected: boolean;
  events: PipelineEvent[];
  connect: (projectId: string) => void;
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

  connect: (projectId: string) => {
    usePipelineStore.getState().disconnect();
    const es = new EventSource(
      `/api/projects/${encodeURIComponent(projectId)}/events`,
    );
    es.onmessage = (e) => {
      try {
        const event: PipelineEvent = JSON.parse(e.data);
        set((state) => ({ events: [...state.events, event] }));
        if (
          event.type === "stage_fail"
          && event.error_code === "insufficient_credits"
          && typeof event.balance_credits === "number"
          && typeof event.required_credits === "number"
        ) {
          // A chained or in-flight stage hit a credit shortfall — surface the
          // buy-credits dialog so the user can top up and continue.
          const stage = event.stage ?? null;
          const stageLabel = stage
            ? (STAGE_DISPLAY_NAMES[stage as StageName] ?? stage)
            : null;
          useInsufficientCreditsStore.getState().show({
            info: {
              balance_credits: event.balance_credits,
              required_credits: event.required_credits,
              shortfall_credits:
                event.shortfall_credits
                ?? Math.max(0, event.required_credits - event.balance_credits),
              stage,
              action: null,
              message: event.message ?? "Insufficient credits",
            },
            actionLabel: stageLabel ? `Run ${stageLabel}` : "Continue pipeline",
          });
        }
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
          usePipelineStore.getState().connect(projectId);
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

import { create } from "zustand";
import { queryClient } from "../api/queryClient";
import { applyPipelineEvent } from "../lib/stageProgress";
import type { ImagePreview, PipelineEvent } from "../types/api";
import { useInsufficientCreditsStore } from "./insufficientCredits";
import { STAGE_DISPLAY_NAMES, type StageName } from "../types/api";
import { invalidateProject, projectPath } from "../api/projectScope";

interface PipelineStore {
  connected: boolean;
  events: PipelineEvent[];
  projectId: string | null;
  imagePreviews: Record<string, ImagePreview>;
  connect: (projectId: string) => void;
  disconnect: () => void;
  clearEvents: () => void;
  /** Drop finished pixels once the card shows its saved file. */
  releaseImagePreview: (target: string, requestId: string) => void;
}

let eventSource: EventSource | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let reconnectDelay = 1000;
let activeProject: string | null = null;
export const PIPELINE_EVENT_LIMIT = 200;

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
  activeProject = null;
}

export const usePipelineStore = create<PipelineStore>((set) => ({
  connected: false,
  events: [],
  projectId: null,
  imagePreviews: {},

  connect: (projectId: string) => {
    const continuing = activeProject === projectId;
    closeCurrentSource();
    activeProject = projectId;
    if (!continuing) {
      reconnectDelay = 1000;
      set({ events: [], imagePreviews: {} });
    }
    set({ connected: false, projectId });
    const es = new EventSource(
      `/api${projectPath(projectId)}/events`,
    );
    es.onmessage = (e) => {
      if (eventSource !== es) return;
      try {
        const event: PipelineEvent = JSON.parse(e.data);
        reconnectDelay = 1000;
        if (event.type === "image_preview" || event.type === "image_preview_clear") {
          if (!event.target || !event.request_id) return;
          set((state) => {
            const imagePreviews = { ...state.imagePreviews };
            const current = imagePreviews[event.target!];
            if (event.type === "image_preview_clear") {
              if (event.settled && current?.request_id === event.request_id && current.preview_index === 3) {
                // Completed pixels of a finished job: hold them until the saved file loads.
                imagePreviews[event.target!] = { ...current, settled: true };
              } else if (event.reset || current?.request_id === event.request_id) delete imagePreviews[event.target!];
            } else if (typeof event.preview_index === "number" && Number.isInteger(event.preview_index) && event.preview_index >= 0 && event.preview_index <= 3
              && event.image_url?.startsWith("data:image/webp;base64,")
              && event.image_url.length <= 2 * 1024 * 1024
              && (!current || current.request_id !== event.request_id || event.preview_index > current.preview_index)) {
              imagePreviews[event.target!] = { request_id: event.request_id!, preview_index: event.preview_index, image_url: event.image_url };
              if (Object.keys(imagePreviews).length > 32) delete imagePreviews[Object.keys(imagePreviews)[0]];
            }
            return { imagePreviews };
          });
          return;
        }
        // Snapshots are state, not history: they live in the status cache and
        // must not evict the log lines this bounded feed exists to keep.
        if (event.type !== "stage_snapshot") {
          set((state) => ({ events: [...state.events.slice(-(PIPELINE_EVENT_LIMIT - 1)), event] }));
        }
        applyPipelineEvent(queryClient, projectId, event);
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
          void invalidateProject(queryClient, projectId, "status");
          void queryClient.invalidateQueries({ queryKey: ["projects"] });
          closeCurrentSource(es);
          set({ connected: false, imagePreviews: {} });
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
      if (eventSource !== es) return;
      reconnectDelay = 1000;
      set({ connected: true });
    };
    eventSource = es;
  },

  disconnect: () => {
    closeCurrentSource();
    reconnectDelay = 1000;
    set({ connected: false, projectId: null, imagePreviews: {} });
  },

  clearEvents: () => set({ events: [], imagePreviews: {} }),

  releaseImagePreview: (target, requestId) => set((state) => {
    const current = state.imagePreviews[target];
    if (!current?.settled || current.request_id !== requestId) return state;
    const imagePreviews = { ...state.imagePreviews };
    delete imagePreviews[target];
    return { imagePreviews };
  }),
}));

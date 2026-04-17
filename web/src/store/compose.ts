import { create } from "zustand";
import type { ComicPage } from "../types/api";

const MAX_UNDO = 50;

interface Selection {
  panelId: string;
  type: "bubble" | "sfx";
  elementId: string;
}

interface ComposeStore {
  selection: Selection | null;
  undoStack: ComicPage[];
  redoStack: ComicPage[];

  select: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  deselect: () => void;
  pushUndo: (page: ComicPage) => void;
  popUndo: () => ComicPage | undefined;
  popRedo: () => ComicPage | undefined;
  clearHistory: () => void;
}

export const useComposeStore = create<ComposeStore>((set, get) => ({
  selection: null,
  undoStack: [],
  redoStack: [],

  select: (panelId, type, elementId) =>
    set({ selection: { panelId, type, elementId } }),

  deselect: () => set({ selection: null }),

  pushUndo: (page) =>
    set((s) => ({
      undoStack: [...s.undoStack.slice(-MAX_UNDO + 1), structuredClone(page)],
      redoStack: [],
    })),

  popUndo: () => {
    const s = get();
    if (s.undoStack.length === 0) return undefined;
    const page = s.undoStack[s.undoStack.length - 1];
    set({
      undoStack: s.undoStack.slice(0, -1),
    });
    return page;
  },

  popRedo: () => {
    const s = get();
    if (s.redoStack.length === 0) return undefined;
    const page = s.redoStack[s.redoStack.length - 1];
    set({
      redoStack: s.redoStack.slice(0, -1),
    });
    return page;
  },

  clearHistory: () => set({ undoStack: [], redoStack: [], selection: null }),
}));

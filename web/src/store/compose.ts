import { create } from "zustand";
import type { ComicPage } from "../types/api";

const MAX_UNDO = 50;

interface Selection {
  panelId: string;
  type: "bubble" | "sfx";
  elementId: string;
}

/**
 * Undo entries are page-scoped: ScriptMode can edit pages other than the one
 * currently shown on the canvas, so undo/redo must restore the snapshot to
 * the page it came from — never to whichever page happens to be visible.
 */
export interface PageSnapshot {
  pageNum: number;
  page: ComicPage;
}

interface ComposeStore {
  selection: Selection | null;
  undoStack: PageSnapshot[];
  redoStack: PageSnapshot[];

  select: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  deselect: () => void;
  pushUndo: (page: ComicPage) => void;
  popUndo: () => PageSnapshot | undefined;
  popRedo: () => PageSnapshot | undefined;
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
      undoStack: [
        ...s.undoStack.slice(-MAX_UNDO + 1),
        { pageNum: page.page_number, page: structuredClone(page) },
      ],
      redoStack: [],
    })),

  popUndo: () => {
    const s = get();
    if (s.undoStack.length === 0) return undefined;
    const snapshot = s.undoStack[s.undoStack.length - 1];
    set({
      undoStack: s.undoStack.slice(0, -1),
    });
    return snapshot;
  },

  popRedo: () => {
    const s = get();
    if (s.redoStack.length === 0) return undefined;
    const snapshot = s.redoStack[s.redoStack.length - 1];
    set({
      redoStack: s.redoStack.slice(0, -1),
    });
    return snapshot;
  },

  clearHistory: () => set({ undoStack: [], redoStack: [], selection: null }),
}));

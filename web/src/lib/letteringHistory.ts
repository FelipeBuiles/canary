import type { PageLettering } from "@lettering-engine";
import { accountIdentity } from "./accountEpoch";
export interface History {
  past: PageLettering[];
  present: PageLettering;
  future: PageLettering[];
  gesture: PageLettering | null;
}
export type HistoryAction = {
  type: "change" | "preview" | "acknowledge" | "reset";
  value: PageLettering;
} | {
  type: "begin" | "commit" | "cancel" | "undo" | "redo";
};
export const initialHistory = (present: PageLettering): History => ({ past: [], present, future: [], gesture: null });
export function editableSignature(state: PageLettering): string {
  return JSON.stringify({ locale: state.locale, elements: state.elements.map(element => { const value: Partial<typeof element> = { ...element }; delete value.resolved; return value; }) });
}
function committed(state: History, next: PageLettering, previous = state.gesture ?? state.present): History {
  if (editableSignature(previous) === editableSignature(next))
    return { ...state, present: next, gesture: null };
  return { past: [...state.past, previous].slice(-80), present: next, future: [], gesture: null };
}
export function historyReducer(state: History, action: HistoryAction): History {
  switch (action.type) {
    case "change": return committed(state, action.value);
    case "preview": return { ...state, present: action.value };
    case "begin": return state.gesture ? state : { ...state, gesture: state.present };
    case "commit": return state.gesture ? committed(state, state.present) : state;
    case "cancel": return state.gesture ? { ...state, present: state.gesture, gesture: null } : state;
    case "acknowledge": return { ...state, present: action.value, gesture: null };
    case "reset": return initialHistory(action.value);
    case "undo": {
      const current = state.gesture ? committed(state, state.present) : state;
      const previous = current.past.at(-1);
      return previous ? { past: current.past.slice(0, -1), present: previous, future: [current.present, ...current.future], gesture: null } : current;
    }
    case "redo": {
      const next = state.future[0];
      return next ? { past: [...state.past, state.present], present: next, future: state.future.slice(1), gesture: null } : state;
    }
  }
}
export interface LetteringDraft {
  version: 1;
  baseRevision: number;
  sourceSha: string;
  styleSha: string;
  imageSha: string;
  state: PageLettering;
  updatedAt: string;
}
export function letteringDraftKey(project: string, page: number) {
  return `canary.lettering-draft:v1:${accountIdentity ?? "signed-out"}:${encodeURIComponent(project)}:${page}`;
}
export function readLetteringDraft(key: string): LetteringDraft | null {
  try {
    const raw = localStorage.getItem(key);
    if (!raw)
      return null;
    const value = JSON.parse(raw) as LetteringDraft;
    if (value.version !== 1 || !Number.isInteger(value.baseRevision) || !Array.isArray(value.state?.elements)
      || !value.state.elements.every(e => typeof e.id === "string" && e.text_by_locale && e.placement && e.suggested_placement))
      return null;
    return value;
  }
  catch {
    return null;
  }
}
export function writeLetteringDraft(key: string, draft: LetteringDraft): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(draft));
    return true;
  }
  catch {
    return false;
  }
}
export function clearLetteringDraft(key: string) {
  try {
    localStorage.removeItem(key);
  }
  catch { /* A saved draft is harmless; compare before offering recovery. */ }
}

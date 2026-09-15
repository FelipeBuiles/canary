import type { LetteringElement, PageLettering, LetteringBox } from "../../api/lettering";

export interface LetteringHistory { past: PageLettering[]; present: PageLettering; future: PageLettering[] }
export type HistoryAction = { type: "edit" | "resolve" | "reset"; value: PageLettering; coalesce?: boolean } | { type: "undo" | "redo" };
export function letteringHistory(state: LetteringHistory, action: HistoryAction): LetteringHistory {
  switch (action.type) {
    case "reset": return { past: [], present: action.value, future: [] };
    case "edit":
      if (action.coalesce && state.past.length) return { ...state, present: action.value, future: [] };
      return { past: [...state.past.slice(-49), state.present], present: action.value, future: [] };
    case "resolve": return { ...state, present: action.value };
    case "undo": {
      const value = state.past.at(-1);
      return value ? { past: state.past.slice(0, -1), present: value, future: [state.present, ...state.future] } : state;
    }
    case "redo": {
      const [value, ...rest] = state.future;
      return value ? { past: [...state.past, state.present], present: value, future: rest } : state;
    }
  }
}
export function draftIdentity(state: PageLettering): string {
  return JSON.stringify({ page: state.page_number, source: state.comic_page_sha256, locale: state.locale,
    style: state.style, reviewed: state.reviewed_against_render_revision,
    elements: state.elements.map(({ resolved: _resolved, ...element }) => { void _resolved; return element; }) });
}
export function moveBox(box: LetteringBox, dx: number, dy: number): LetteringBox {
  return { ...box, x: Math.max(0, Math.min(1 - box.width, box.x + dx)), y: Math.max(0, Math.min(1 - box.height, box.y + dy)) };
}
export function resizeBox(box: LetteringBox, dx: number, dy: number): LetteringBox {
  return { ...box, width: Math.min(1 - box.x, Math.max(.035, box.width + dx)), height: Math.min(1 - box.y, Math.max(.025, box.height + dy)) };
}
export function elementCopy(element: LetteringElement, state: PageLettering, canonical: Record<string, string>): string {
  return element.copies[state.locale] ?? (state.locale ? "" : canonical[element.source_lettering_item_id ?? ""] ?? "");
}


export interface LocalLetteringDraft { base_sha256: string | null; state: PageLettering }
export function readLocalDraft(key: string): LocalLetteringDraft | null {
  try {
    const value = JSON.parse(sessionStorage.getItem(key) ?? "null") as LocalLetteringDraft | null;
    if (!value?.state?.style || !Array.isArray(value.state.elements) || typeof value.state.comic_page_sha256 !== "string") return null;
    if (!value.state.elements.every((e) => e.id && e.placement && e.suggested_placement && e.copies && e.resolved)) return null;
    return value;
  } catch { return null; }
}
export function downloadLetteringDraft(state: PageLettering) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(state, null, 2)], { type: "application/json" }));
  const link = document.createElement("a");
  link.href = url; link.download = `page-${state.page_number}-lettering-draft.json`;
  link.click(); URL.revokeObjectURL(url);
}

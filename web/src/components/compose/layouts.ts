/** Grid layout definitions — ported from Python html_renderer.py _STATIC_CSS layout classes */

import type { CSSProperties } from "react";

export const PAGE_W = 2480;
export const PAGE_H = 3508;

export type LayoutId = "1" | "2" | "3" | "4" | "5" | "6" | "many";
export const LAYOUT_IDS: LayoutId[] = ["1", "2", "3", "4", "5", "6", "many"];

export const LAYOUT_DISPLAY: Record<LayoutId, string> = {
  "1": "1 Panel",
  "2": "2 Panels",
  "3": "3 Panels",
  "4": "4 Panels",
  "5": "5 Panels",
  "6": "6 Panels",
  many: "Many (>6)",
};

interface LayoutDef {
  /** CSS Grid template for the page */
  gridStyle: CSSProperties;
  /** Returns grid-column override for nth panel (0-indexed), or undefined for auto */
  gridColumnOverride: (index: number) => string | undefined;
  /** Returns grid-row override for nth panel (0-indexed), or undefined for auto */
  gridRowOverride: (index: number) => string | undefined;
}

const noOverride = () => undefined;

export const LAYOUTS: Record<string, LayoutDef> = {
  "1": {
    gridStyle: {
      gridTemplateRows: "1fr",
      gridTemplateColumns: "1fr",
    },
    gridColumnOverride: noOverride,
    gridRowOverride: noOverride,
  },
  "2": {
    gridStyle: {
      gridTemplateRows: "1fr 1fr",
      gridTemplateColumns: "1fr",
    },
    gridColumnOverride: noOverride,
    gridRowOverride: noOverride,
  },
  "3": {
    gridStyle: {
      gridTemplateRows: "1fr 1fr",
      gridTemplateColumns: "1fr 1fr",
    },
    gridColumnOverride: (i) => (i === 0 ? "1 / 3" : undefined),
    gridRowOverride: noOverride,
  },
  "4": {
    gridStyle: {
      gridTemplateRows: "1fr 1fr",
      gridTemplateColumns: "1fr 1fr",
    },
    gridColumnOverride: noOverride,
    gridRowOverride: noOverride,
  },
  "5": {
    gridStyle: {
      gridTemplateRows: "1fr 1fr",
      gridTemplateColumns: "1fr 1fr 1fr",
    },
    gridColumnOverride: (i) => {
      if (i === 0) return "1 / 3";
      if (i === 1) return "3";
      return undefined;
    },
    gridRowOverride: noOverride,
  },
  "6": {
    gridStyle: {
      gridTemplateRows: "1fr 1fr",
      gridTemplateColumns: "1fr 1fr 1fr",
    },
    gridColumnOverride: noOverride,
    gridRowOverride: noOverride,
  },
  many: {
    gridStyle: {
      gridAutoRows: "1fr",
      gridTemplateColumns: "1fr 1fr 1fr",
    },
    gridColumnOverride: noOverride,
    gridRowOverride: noOverride,
  },
};

export function getLayout(id: string): LayoutDef {
  return LAYOUTS[id] ?? LAYOUTS["4"];
}

/** Resolve grid placement for a panel. Inline style (from editor) takes precedence. */
export function resolveGridPlacement(
  layoutId: string,
  panelIndex: number,
  gridColumn: string | null,
  gridRow: string | null,
): CSSProperties {
  const layout = getLayout(layoutId);
  const col = gridColumn ?? layout.gridColumnOverride(panelIndex);
  const row = gridRow ?? layout.gridRowOverride(panelIndex);
  const style: CSSProperties = {};
  if (col) style.gridColumn = col;
  if (row) style.gridRow = row;
  return style;
}

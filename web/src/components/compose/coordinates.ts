/** Screen↔page coordinate transforms */

import { PAGE_W, PAGE_H } from "./layouts";

/** Convert a client-space pointer position to page-space coordinates */
export function clientToPage(
  clientX: number,
  clientY: number,
  containerRect: DOMRect,
  scale: number,
): { x: number; y: number } {
  return {
    x: (clientX - containerRect.left) / scale,
    y: (clientY - containerRect.top) / scale,
  };
}

/** Convert page-space coordinates to panel-relative coordinates */
export function pageToPanel(
  pageX: number,
  pageY: number,
  panelRect: DOMRect,
  scale: number,
): { x: number; y: number } {
  return {
    x: pageX - panelRect.left / scale,
    y: pageY - panelRect.top / scale,
  };
}

/** Compute the scale factor to fit the page within a container */
export function computeScale(containerW: number, containerH: number): number {
  const s = Math.min(containerW / PAGE_W, containerH / PAGE_H);
  return isFinite(s) && s > 0 ? s : 0;
}

/** Check if pointer moved more than threshold (px, screen-space) */
export function exceedsThreshold(dx: number, dy: number, threshold = 3): boolean {
  return Math.abs(dx) > threshold || Math.abs(dy) > threshold;
}

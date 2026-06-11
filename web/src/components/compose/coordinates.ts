/** Screen↔page coordinate transforms */

import { PAGE_W, PAGE_H } from "./layouts";

/** Compute the scale factor to fit native content within a container */
export function computeScale(
  containerW: number,
  containerH: number,
  nativeW: number = PAGE_W,
  nativeH: number = PAGE_H,
): number {
  const s = Math.min(containerW / nativeW, containerH / nativeH);
  return isFinite(s) && s > 0 ? s : 0;
}

/** Check if pointer moved more than threshold (px, screen-space) */
export function exceedsThreshold(dx: number, dy: number, threshold = 3): boolean {
  return Math.abs(dx) > threshold || Math.abs(dy) > threshold;
}

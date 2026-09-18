import type { PageCorrectionAnnotation } from "../../api/pages";
import { MAX_ANNOTATION_POINTS, MIN_POINTS, roundPoint } from "./annotationGeometry";

export const MAX_CORRECTION_MARKS = 24;
export const MAX_CORRECTION_CHANGES = 24;
export const MAX_CORRECTION_INSTRUCTION = 1000;
export const MAX_MARK_NOTE = 500;

/** Keep geometry private to the provider, and never silently omit a location. */
export function annotationProblem(mark: PageCorrectionAnnotation): string | null {
  const minimum = MIN_POINTS[mark.kind];
  if (!minimum || mark.points.length < minimum || mark.points.length > MAX_ANNOTATION_POINTS
    || (mark.kind === "pin" && mark.points.length !== 1)) {
    return "This location is unfinished. Remove it or draw it again.";
  }
  if (mark.points.some(({ x, y }) => !Number.isFinite(x) || !Number.isFinite(y))) {
    return "This location is invalid. Remove it or draw it again.";
  }
  const points = mark.points.map(roundPoint);
  if (mark.kind !== "pin") {
    const width = Math.max(...points.map((p) => p.x)) - Math.min(...points.map((p) => p.x));
    const height = Math.max(...points.map((p) => p.y)) - Math.min(...points.map((p) => p.y));
    if (width <= 0 && height <= 0) return "This location is too small. Remove it or draw it again.";
    if ((mark.kind === "rectangle" || mark.kind === "highlight") && (width <= 0 || height <= 0)) {
      return "An area needs both width and height. Remove it or draw it again.";
    }
  }
  if ((mark.note ?? "").trim().length > MAX_MARK_NOTE) {
    return "Shorten the extra location detail to 500 characters.";
  }
  return null;
}

/**
 * A location belongs to a change, whose full instruction is already in the
 * prompt. The API requires a nonblank mark note, not another author input.
 * A short relational note also handles 501–1000 character parent requests
 * without truncating or duplicating the author's instruction.
 */
export function serializeAnnotation(mark: PageCorrectionAnnotation): PageCorrectionAnnotation {
  const problem = annotationProblem(mark);
  if (problem) throw new Error(problem);
  return {
    id: mark.id,
    kind: mark.kind,
    points: mark.points.map(roundPoint),
    note: mark.note?.trim() || "Apply the enclosing change request at this location.",
    ...(mark.label ? { label: mark.label } : {}),
  };
}

/** Translate the whole shape without squashing it against a page edge. */
export function moveAnnotation(mark: PageCorrectionAnnotation, dx: number, dy: number): PageCorrectionAnnotation {
  if (mark.points.length === 0) return mark;
  const xs = mark.points.map((p) => p.x);
  const ys = mark.points.map((p) => p.y);
  const x = Math.max(-Math.min(...xs), Math.min(dx, 1 - Math.max(...xs)));
  const y = Math.max(-Math.min(...ys), Math.min(dy, 1 - Math.max(...ys)));
  return { ...mark, points: mark.points.map((p) => roundPoint({ x: p.x + x, y: p.y + y })) };
}

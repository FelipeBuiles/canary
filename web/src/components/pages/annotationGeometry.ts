import type { PageAnnotationKind, PageCorrectionAnnotation } from "../../api/pages";

export type EditorAnnotation = PageCorrectionAnnotation;

export const MIN_POINTS: Record<PageAnnotationKind, number> = {
  pin: 1,
  rectangle: 2,
  highlight: 2,
  freehand: 2,
  arrow: 2,
};

/** Backend geometry limit per annotation; longer strokes are thinned, never dropped. */
export const MAX_ANNOTATION_POINTS = 64;

/** Minimum normalized move before a freehand stroke records another point. */
export const FREEHAND_STEP = 0.004;

export function roundPoint(point: { x: number; y: number }) {
  return {
    x: Math.min(1, Math.max(0, Math.round(point.x * 10000) / 10000)),
    y: Math.min(1, Math.max(0, Math.round(point.y * 10000) / 10000)),
  };
}

/** Stride-sample long strokes to the cap, always keeping both endpoints. */
export function simplifyStroke(points: { x: number; y: number }[]): { points: { x: number; y: number }[]; simplified: boolean } {
  if (points.length <= MAX_ANNOTATION_POINTS) return { points, simplified: false };
  const stride = (points.length - 1) / (MAX_ANNOTATION_POINTS - 1);
  const sampled = [points[0]!];
  for (let index = 1; index < MAX_ANNOTATION_POINTS - 1; index += 1) {
    sampled.push(points[Math.round(index * stride)]!);
  }
  sampled.push(points[points.length - 1]!);
  return { points: sampled, simplified: true };
}

export function newAnnotationId(kind: string): string {
  const rand = Math.floor(Math.random() * 1e9).toString(36);
  return `mark-${kind}-${Date.now().toString(36)}-${rand}`;
}

export function normalizeForSubmit(annotations: EditorAnnotation[]): EditorAnnotation[] {
  return annotations
    .filter((mark) => mark.points.length >= MIN_POINTS[mark.kind])
    .map((mark) => ({ ...mark, points: mark.points.map(roundPoint) }));
}

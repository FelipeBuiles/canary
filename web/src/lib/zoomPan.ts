/** Geometry for a zoomable, pannable image drawn at `scale` natural pixels with its top-left at (x, y). */
export interface Size { width: number; height: number }
export interface Point { x: number; y: number }
export interface ZoomView { scale: number; x: number; y: number }

/** Breathing room around a fitted image so it never touches the viewer chrome. */
export const FIT_PADDING = 16;
export const ZOOM_STEP = 1.5;

export function fitScale(image: Size, stage: Size): number {
  const width = Math.max(stage.width - FIT_PADDING * 2, 1);
  const height = Math.max(stage.height - FIT_PADDING * 2, 1);
  return Math.min(width / image.width, height / image.height);
}

/** Never smaller than fitted or 1:1, never so large that a pixel stops reading as image. */
export function scaleLimits(fit: number) {
  return { min: Math.min(fit, 1), max: Math.max(fit * 8, 8) };
}

/** Center an axis that fits; otherwise keep the image edge from leaving the stage edge. */
function clampAxis(offset: number, drawn: number, stage: number) {
  if (drawn <= stage) return (stage - drawn) / 2;
  return Math.min(0, Math.max(stage - drawn, offset));
}

export function clampView(view: ZoomView, image: Size, stage: Size): ZoomView {
  return {
    scale: view.scale,
    x: clampAxis(view.x, image.width * view.scale, stage.width),
    y: clampAxis(view.y, image.height * view.scale, stage.height),
  };
}

export function centeredView(scale: number, image: Size, stage: Size): ZoomView {
  return clampView({ scale, x: 0, y: 0 }, image, stage);
}

/** Zoom so the image point under `anchor` (stage coordinates) stays under it. */
export function zoomAt(view: ZoomView, scale: number, anchor: Point, image: Size, stage: Size): ZoomView {
  const { min, max } = scaleLimits(fitScale(image, stage));
  const next = Math.min(max, Math.max(min, scale));
  const ratio = next / view.scale;
  return clampView({
    scale: next,
    x: anchor.x - (anchor.x - view.x) * ratio,
    y: anchor.y - (anchor.y - view.y) * ratio,
  }, image, stage);
}

/** The part of the image currently on stage, as fractions of the image. */
export function visibleRegion(view: ZoomView, image: Size, stage: Size) {
  const drawnWidth = image.width * view.scale, drawnHeight = image.height * view.scale;
  const left = Math.max(0, -view.x / drawnWidth), top = Math.max(0, -view.y / drawnHeight);
  return {
    left,
    top,
    width: Math.min(1 - left, stage.width / drawnWidth),
    height: Math.min(1 - top, stage.height / drawnHeight),
  };
}

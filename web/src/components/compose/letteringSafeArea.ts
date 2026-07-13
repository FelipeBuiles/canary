const SAFE_GUTTER_PX = 8;

type SafeAreaStatus = "verified" | "failed" | "unsupported";

function sampleLine(start: [number, number], end: [number, number]) {
  const distance = Math.hypot(end[0] - start[0], end[1] - start[1]);
  const segments = Math.max(1, Math.ceil(distance / SAFE_GUTTER_PX));
  return Array.from({ length: segments + 1 }, (_, index) => {
    const fraction = index / segments;
    return [
      start[0] + (end[0] - start[0]) * fraction,
      start[1] + (end[1] - start[1]) * fraction,
    ] as [number, number];
  });
}

function perimeterPoints(rect: DOMRect) {
  const left = rect.left - SAFE_GUTTER_PX;
  const right = rect.right + SAFE_GUTTER_PX;
  const top = rect.top - SAFE_GUTTER_PX;
  const bottom = rect.bottom + SAFE_GUTTER_PX;
  return [
    ...sampleLine([left, top], [right, top]),
    ...sampleLine([right, top], [right, bottom]),
    ...sampleLine([right, bottom], [left, bottom]),
    ...sampleLine([left, bottom], [left, top]),
  ];
}

/** Validate the text safe rectangle against the actual SVG fill without changing layout. */
export function verifyLetteringSafeArea(host: HTMLElement): SafeAreaStatus {
  const content = host.querySelector<HTMLElement>(":scope > .letter-content");
  const path = host.querySelector<SVGGeometryElement>(":scope > .letter-shape path");
  if (!content || !path || typeof path.isPointInFill !== "function" || typeof DOMPoint === "undefined") {
    host.dataset.safeArea = "unsupported";
    return "unsupported";
  }
  const matrix = path.getScreenCTM();
  if (!matrix) {
    host.dataset.safeArea = "unsupported";
    return "unsupported";
  }
  const inverse = matrix.inverse();
  const safe = perimeterPoints(content.getBoundingClientRect()).every(([x, y]) =>
    path.isPointInFill(new DOMPoint(x, y).matrixTransform(inverse)),
  );
  host.dataset.safeArea = safe ? "verified" : "failed";
  return safe ? "verified" : "failed";
}

export function verifyLetteringSafeAreas(root: ParentNode) {
  return [...root.querySelectorAll<HTMLElement>(".bubble, .caption")].map(verifyLetteringSafeArea);
}

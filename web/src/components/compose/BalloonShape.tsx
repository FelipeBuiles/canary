import type { Bubble } from "../../types/api";

const SPEECH_SHAPE_PATH =
  "M4 1 C30 0 70 0 94 2 C99 3 100 6 100 12 L100 88 C100 95 96 99 89 100 C62 100 31 100 9 99 C3 98 0 95 0 88 L0 12 C0 5 1 2 4 1 Z";
const THOUGHT_SHAPE_PATH =
  "M18 2 C8 2 2 10 2 22 L2 78 C2 90 8 98 18 98 L82 98 C92 98 98 90 98 78 L98 22 C98 10 92 2 82 2 Z";
const NARRATION_SHAPE_PATH = "M2 4 L96 2 L99 88 L92 98 L3 96 Z";

export function BalloonShape({ type }: { type: Bubble["type"] }) {
  const narration = type === "narration";
  const path = narration
    ? NARRATION_SHAPE_PATH
    : type === "thought"
      ? THOUGHT_SHAPE_PATH
      : SPEECH_SHAPE_PATH;

  return (
    <svg
      className="letter-shape"
      viewBox="0 0 100 100"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <path
        d={path}
        fill={narration ? "var(--caption-bg)" : "var(--bubble-bg)"}
        stroke={narration ? "var(--caption-border)" : "var(--bubble-border)"}
        strokeWidth={narration ? "var(--caption-border-width, 2px)" : "var(--bubble-border-width)"}
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

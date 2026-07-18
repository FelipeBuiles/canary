import type { Bubble } from "../../types/api";

const SPEECH_SHAPE_PATH =
  "M4 1 C30 0 70 0 94 2 C99 3 100 6 100 12 L100 88 C100 95 96 99 89 100 C62 100 31 100 9 99 C3 98 0 95 0 88 L0 12 C0 5 1 2 4 1 Z";
const THOUGHT_SHAPE_PATH =
  "M4 50 C-2 39 1 27 10 22 C7 10 17 2 29 6 C38 -1 52 0 59 7 C71 1 85 5 89 16 C99 19 102 32 95 41 C102 50 100 62 92 68 C96 80 85 91 73 88 C65 98 50 100 41 92 C29 98 16 92 13 82 C2 81 -3 69 3 59 C-1 56 -1 52 4 50 Z";
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

export function AutoSpeechTail() {
  return (
    <svg
      className="auto-tail"
      viewBox="0 0 54 46"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <path
        d="M13 0 C13 15 7 32 2 44 C16 37 29 21 36 0 Z"
        fill="var(--bubble-bg)"
        stroke="var(--bubble-border)"
        strokeWidth="var(--bubble-border-width)"
        vectorEffect="non-scaling-stroke"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}

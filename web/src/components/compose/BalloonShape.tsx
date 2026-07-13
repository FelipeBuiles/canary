import type { Bubble } from "../../types/api";

const SPEECH_SHAPE_PATH =
  "M8 2 C32 0 68 1 90 3 C96 4 98 7 98 14 L98 84 C98 92 94 97 86 98 C60 100 30 100 12 98 C5 97 2 93 2 85 L2 14 C2 7 4 3 8 2 Z";
const THOUGHT_SHAPE_PATH =
  "M8 47 C2 38 6 27 16 24 C18 5 30 3 40 8 C48 2 62 3 68 11 C80 5 92 14 91 28 C99 39 99 51 92 57 C96 68 88 81 78 81 C73 92 58 94 49 86 C39 94 25 92 22 84 C12 84 4 73 8 63 C1 58 1 51 8 47 Z";
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

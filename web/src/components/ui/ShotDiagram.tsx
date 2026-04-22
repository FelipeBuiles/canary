import { cn } from "../../lib/cn";

export type ShotType = "XW" | "W" | "MC" | "CU" | "XCU" | "UNKNOWN";

interface ShotDiagramProps {
  shot: string;
  className?: string;
  size?: number;
}

/**
 * Normalize backend shot_type strings (`extreme-wide`, `close-up`, etc.)
 * into one of five glyph buckets.
 */
function normalizeShotType(shot: string | undefined | null): ShotType {
  if (!shot) return "UNKNOWN";
  const s = shot.toLowerCase().replace(/[_\s]+/g, "-");
  if (s.includes("extreme-wide") || s === "xw" || s.includes("establishing")) return "XW";
  if (s.includes("extreme-close") || s === "xcu" || s.includes("macro")) return "XCU";
  if (s.includes("close") || s === "cu") return "CU";
  if (s.includes("medium") || s === "mc" || s === "m") return "MC";
  if (s.includes("wide") || s === "w") return "W";
  return "UNKNOWN";
}

const LABEL: Record<ShotType, string> = {
  XW: "XW",
  W: "W",
  MC: "MC",
  CU: "CU",
  XCU: "XCU",
  UNKNOWN: "—",
};

/**
 * Small SVG glyph showing the relative size of a subject in frame.
 * Ink-black frame, silhouette filled in hero-red to match the brand.
 */
export function ShotDiagram({ shot, className, size = 32 }: ShotDiagramProps) {
  const kind = normalizeShotType(shot);
  return (
    <div
      className={cn(
        "inline-flex flex-col items-center gap-1 font-meta leading-none",
        className,
      )}
      title={`Shot: ${shot || "unknown"}`}
    >
      <svg
        viewBox="0 0 40 32"
        width={size}
        height={(size * 32) / 40}
        className="block border-[1.5px] border-ink-black bg-bristol"
        aria-label={`Shot type ${kind}`}
      >
        {renderSilhouette(kind)}
      </svg>
      <span className="text-[0.52rem] tracking-[0.16em] text-ink-black/60">
        {LABEL[kind]}
      </span>
    </div>
  );
}

function renderSilhouette(kind: ShotType) {
  const fill = "var(--color-hero-red)";
  switch (kind) {
    case "XW":
      return (
        <>
          {/* horizon line + tiny figure */}
          <line x1="0" y1="26" x2="40" y2="26" stroke="var(--color-ink-black)" strokeWidth="1" />
          <circle cx="20" cy="22" r="1.2" fill={fill} />
          <rect x="19.3" y="22" width="1.4" height="3.2" fill={fill} />
        </>
      );
    case "W":
      return (
        <>
          <line x1="0" y1="28" x2="40" y2="28" stroke="var(--color-ink-black)" strokeWidth="1" />
          <circle cx="20" cy="17" r="2.4" fill={fill} />
          <rect x="18" y="18.5" width="4" height="9.5" fill={fill} />
        </>
      );
    case "MC":
      return (
        <>
          <circle cx="20" cy="12" r="4" fill={fill} />
          <path d="M12 32 L12 22 Q12 17 20 17 Q28 17 28 22 L28 32 Z" fill={fill} />
        </>
      );
    case "CU":
      return (
        <>
          <circle cx="20" cy="16" r="10" fill={fill} />
          <path d="M6 32 L6 28 Q6 24 20 24 Q34 24 34 28 L34 32 Z" fill={fill} />
        </>
      );
    case "XCU":
      return (
        <>
          <circle cx="20" cy="18" r="18" fill={fill} />
        </>
      );
    default:
      return (
        <text
          x="20"
          y="21"
          textAnchor="middle"
          fontSize="12"
          fill="var(--color-ink-black)"
          fontFamily="var(--font-meta)"
        >
          ?
        </text>
      );
  }
}

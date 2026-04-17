import type { Bubble } from "../../types/api";

interface SvgTailProps {
  bubble: Bubble;
}

/**
 * SVG tail for pinned bubbles with tail_x/tail_y.
 * Ported from Python html_renderer._svg_tail().
 */
export function SvgTail({ bubble }: SvgTailProps) {
  if (bubble.tail_x == null || bubble.tail_y == null) return null;
  if (bubble.x == null || bubble.y == null) return null;

  const bw = bubble.width ?? 200;
  const tx = bubble.tail_x - bubble.x;
  const ty = bubble.tail_y - bubble.y;

  const targetBelow = ty > 20;
  const hw = 10;

  let anchorCss: React.CSSProperties;
  let tipX: number;
  let tipY: number;

  if (targetBelow) {
    anchorCss = { left: "50%", bottom: 0, transform: "translate(-50%, 100%)" };
    tipX = tx - bw / 2;
    tipY = ty - 50;
  } else {
    anchorCss = { left: "50%", top: 0, transform: "translate(-50%, -100%)" };
    tipX = tx - bw / 2;
    tipY = ty;
  }

  const points = `${-hw},0 ${hw},0 ${tipX},${tipY}`;

  return (
    <svg className="tail-svg" style={anchorCss} viewBox="0 0 0 0">
      <polygon
        points={points}
        fill="var(--bubble-bg)"
        stroke="var(--bubble-border)"
        strokeWidth="var(--bubble-border-width)"
        strokeLinejoin="round"
      />
    </svg>
  );
}

import { useLayoutEffect, useRef, useState } from "react";
import type { Bubble } from "../../types/api";
import { pinnedTailPath } from "./tailPath";

interface SvgTailProps {
  bubble: Bubble;
}

/** Curved SVG tail whose tip lands exactly on the panel-relative target. */
export function SvgTail({ bubble }: SvgTailProps) {
  const ref = useRef<SVGSVGElement>(null);
  const [path, setPath] = useState("");

  useLayoutEffect(() => {
    const svg = ref.current;
    const element = svg?.parentElement;
    if (!svg || !element || bubble.tail_x == null || bubble.tail_y == null) return;

    const update = () => {
      const targetX = bubble.tail_x! - element.offsetLeft;
      const targetY = bubble.tail_y! - element.offsetTop;
      setPath(pinnedTailPath(element.offsetWidth, element.offsetHeight, targetX, targetY));
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, [bubble.tail_x, bubble.tail_y, bubble.x, bubble.y, bubble.width, bubble.text]);

  if (bubble.tail_x == null || bubble.tail_y == null) return null;
  if (bubble.x == null || bubble.y == null) return null;

  return (
    <svg ref={ref} className="tail-svg" aria-hidden="true">
      <path
        className="tail-path"
        d={path}
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

import { useLayoutEffect, useRef, useState } from "react";
import type { Bubble } from "../../types/api";
import { speechTailGeometry, thoughtTailDots } from "./tailPath";

type TailBubble = Pick<Bubble, "type" | "side" | "tail_direction" | "tail_x" | "tail_y"> &
  Partial<Pick<Bubble, "x" | "y" | "width" | "text">>;

interface SvgTailProps {
  bubble: TailBubble;
  selected?: boolean;
}

interface TailGeometry {
  fillPath: string;
  outlinePath: string;
  dots: ReturnType<typeof thoughtTailDots>;
  target: { x: number; y: number; panelX: number; panelY: number } | null;
}

function inferredSpeakerTarget(element: HTMLElement, panel: HTMLElement, bubble: TailBubble) {
  const sideX = bubble.side === "right" ? 0.76 : bubble.side === "center" ? 0.5 : 0.24;
  const bubbleCenterY = element.offsetTop + element.offsetHeight / 2;
  const proxyPanelY = bubble.tail_direction === "up"
    ? panel.clientHeight * 0.32
    : bubble.tail_direction === "down"
      ? panel.clientHeight * 0.68
      : bubbleCenterY < panel.clientHeight * 0.55
        ? panel.clientHeight * 0.68
        : panel.clientHeight * 0.32;
  const center = { x: element.offsetWidth / 2, y: element.offsetHeight / 2 };
  const proxy = {
    x: panel.clientWidth * sideX - element.offsetLeft,
    y: proxyPanelY - element.offsetTop,
  };
  const dx = proxy.x - center.x;
  const dy = proxy.y - center.y;
  const distance = Math.max(1, Math.hypot(dx, dy));
  const pointerLength = Math.max(90, Math.min(220, Math.min(panel.clientWidth, panel.clientHeight) * 0.18));
  return {
    x: center.x + (dx / distance) * pointerLength,
    y: center.y + (dy / distance) * pointerLength,
  };
}

/** Measured speaker indicator shared by automatic and explicitly targeted bubbles. */
export function SpeakerTail({ bubble, selected = false }: SvgTailProps) {
  const ref = useRef<SVGSVGElement>(null);
  const [geometry, setGeometry] = useState<TailGeometry>({ fillPath: "", outlinePath: "", dots: [], target: null });

  useLayoutEffect(() => {
    const svg = ref.current;
    const element = svg?.parentElement;
    if (!svg || !element) return;

    const update = () => {
      const panel = element.closest<HTMLElement>(".panel");
      if (panel && bubble.x != null && bubble.y != null) {
        const gutter = 8;
        const maxLeft = Math.max(gutter, panel.clientWidth - element.offsetWidth - gutter);
        const maxTop = Math.max(gutter, panel.clientHeight - element.offsetHeight - gutter);
        element.style.left = `${Math.min(maxLeft, Math.max(gutter, element.offsetLeft))}px`;
        element.style.top = `${Math.min(maxTop, Math.max(gutter, element.offsetTop))}px`;
      }
      if (!panel) return;
      const target = bubble.tail_x != null && bubble.tail_y != null
        ? { x: bubble.tail_x - element.offsetLeft, y: bubble.tail_y - element.offsetTop }
        : inferredSpeakerTarget(element, panel, bubble);
      const measuredTarget = {
        ...target,
        panelX: target.x + element.offsetLeft,
        panelY: target.y + element.offsetTop,
      };
      if (bubble.type === "thought") {
        setGeometry({
          fillPath: "",
          outlinePath: "",
          dots: thoughtTailDots(element.offsetWidth, element.offsetHeight, target.x, target.y),
          target: measuredTarget,
        });
      } else {
        setGeometry({
          ...speechTailGeometry(element.offsetWidth, element.offsetHeight, target.x, target.y),
          dots: [],
          target: measuredTarget,
        });
      }
    };
    update();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(update);
    observer.observe(element);
    const panel = element.closest<HTMLElement>(".panel");
    if (panel) observer.observe(panel);
    return () => observer.disconnect();
  }, [bubble.side, bubble.tail_direction, bubble.tail_x, bubble.tail_y, bubble.type, bubble.x, bubble.y, bubble.width, bubble.text]);

  if (bubble.type === "narration") return null;

  return (
    <svg ref={ref} className="speaker-tail" aria-hidden="true">
      {geometry.fillPath && <path className="tail-fill" d={geometry.fillPath} fill="var(--bubble-bg)" />}
      {geometry.outlinePath && (
        <path
          className="tail-outline"
          d={geometry.outlinePath}
          fill="none"
          stroke="var(--bubble-border)"
          strokeWidth="var(--bubble-border-width)"
          vectorEffect="non-scaling-stroke"
          strokeLinejoin="round"
          strokeLinecap="round"
        />
      )}
      {geometry.dots.map((dot, index) => (
        <circle
          key={index}
          className="thought-dot"
          cx={dot.cx}
          cy={dot.cy}
          r={dot.radius}
          fill="var(--bubble-bg)"
          stroke="var(--bubble-border)"
          strokeWidth="var(--bubble-border-width)"
          vectorEffect="non-scaling-stroke"
        />
      ))}
      {selected && geometry.target && (
        <circle
          className="tail-target-handle"
          data-tail-handle
          data-tail-panel-x={geometry.target.panelX}
          data-tail-panel-y={geometry.target.panelY}
          cx={geometry.target.x}
          cy={geometry.target.y}
          r={9}
          vectorEffect="non-scaling-stroke"
        />
      )}
    </svg>
  );
}

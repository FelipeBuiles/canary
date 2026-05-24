import type { CSSProperties, ReactNode } from "react";
import { useEffect, useRef } from "react";
import { cn } from "../../lib/cn";

type ColorCluster = {
  x: number;
  y: number;
  r: number;
  color: string;
};

interface FlowingDotsPlaceholderProps {
  aspect?: string;
  className?: string;
  label?: ReactNode;
  caption?: ReactNode;
  "aria-label"?: string;
}

const CLUSTERS: ColorCluster[] = [
  { x: 0.5, y: 0.28, r: 0.2, color: "#F3C23A" },
  { x: 0.18, y: 0.72, r: 0.18, color: "#2C56AF" },
  { x: 0.78, y: 0.74, r: 0.18, color: "#DC4637" },
];

const BACKGROUND = "#0a0a0c";
const HIGHLIGHT = "#E8DEC4";
const LABEL_COLOR = "#F3C23A";
const DENSITY = 8;
const SPEED = 2;

function hexToRgb(hex: string): [number, number, number] {
  const raw = hex.replace("#", "");
  const normalized = raw.length === 3
    ? raw.split("").map((char) => char + char).join("")
    : raw;
  const value = parseInt(normalized, 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

export function FlowingDotsPlaceholder({
  aspect = "4 / 5",
  className,
  label = "GENERATING…",
  caption,
  "aria-label": ariaLabel = "Image generation in progress",
}: FlowingDotsPlaceholderProps) {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number>(0);

  useEffect(() => {
    const canvas = canvasRef.current;
    const wrap = wrapRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !wrap || !ctx) return;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let width = 0;
    let height = 0;

    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas.width = Math.max(1, Math.floor(width * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const flow = (x: number, y: number, t: number) =>
      Math.sin(x * 2.2 + t * 0.34) * 0.55 +
      Math.cos(y * 2.4 - t * 0.24) * 0.48 +
      Math.sin((x + y) * 1.55 + t * 0.2) * 0.38;

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(wrap);

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const highlightRgb = hexToRgb(HIGHLIGHT);

    const draw = (now: number) => {
      if (!startRef.current) startRef.current = now;
      const motionSpeed = reducedMotion ? 0.12 : SPEED;
      const t = ((now - startRef.current) / 1000) * motionSpeed;
      const clusterState = CLUSTERS.map((cluster, index) => ({
        x: cluster.x + Math.sin(t * 0.32 + index * 1.9) * 0.025,
        y: cluster.y + Math.cos(t * 0.3 + index * 1.4) * 0.022,
        r: cluster.r,
        rgb: hexToRgb(cluster.color),
      }));

      ctx.fillStyle = BACKGROUND;
      ctx.fillRect(0, 0, width, height);

      const cellSize = width / DENSITY;
      const cols = Math.max(1, Math.ceil(width / cellSize));
      const rows = Math.max(1, Math.ceil(height / cellSize));
      const xStart = (width - cols * cellSize) / 2;
      const yStart = (height - rows * cellSize) / 2;
      const baseRadius = cellSize * 0.32;

      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          const px = xStart + col * cellSize + cellSize * 0.5;
          const baseY = yStart + row * cellSize + cellSize * 0.5;
          const nx = px / Math.max(width, 1);
          const ny = baseY / Math.max(height, 1);
          const py = baseY + flow(nx, ny, t) * cellSize * 0.5;

          let bestRgb: [number, number, number] | null = null;
          let bestWeight = 0;
          let totalWeight = 0;

          for (const cluster of clusterState) {
            const dx = nx - cluster.x;
            const dy = ny - cluster.y;
            const distance = Math.sqrt(dx * dx + dy * dy);
            const influence = Math.max(0, 1 - distance / (cluster.r * 1.85));
            const weight = influence * influence;
            totalWeight += weight;
            if (weight > bestWeight) {
              bestWeight = weight;
              bestRgb = cluster.rgb;
            }
          }

          const riverY = 0.5 + Math.sin(nx * 4.5 + t * 0.28) * 0.06;
          const river = Math.exp(-Math.pow((ny - riverY) / 0.075, 2));

          let rgb: [number, number, number];
          let alpha: number;
          if (river > bestWeight * 1.12) {
            rgb = highlightRgb;
            alpha = Math.min(0.95, river);
          } else if (bestRgb && totalWeight >= 0.035) {
            rgb = bestRgb;
            alpha = Math.min(1, bestWeight * 1.55);
          } else {
            continue;
          }

          if (alpha < 0.04) continue;

          const pulse = 0.88 + 0.12 * Math.sin(t * 0.8 + (col + row) * 0.16);
          const radius = baseRadius * (0.55 + alpha * 0.9) * pulse;

          ctx.beginPath();
          ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
          ctx.arc(px, py, radius, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      rafRef.current = requestAnimationFrame(draw);
    };

    rafRef.current = requestAnimationFrame(draw);

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      observer.disconnect();
    };
  }, []);

  const style = { aspectRatio: aspect } satisfies CSSProperties;

  return (
    <div
      ref={wrapRef}
      role="img"
      aria-label={ariaLabel}
      className={cn("relative w-full overflow-hidden bg-ink-black", className)}
      style={style}
    >
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="block h-full w-full"
      />
      {(label || caption) && (
        <div
          className="absolute inset-0 flex flex-col items-center justify-center px-4 text-center"
          style={{
            background:
              "radial-gradient(circle at center, rgba(10, 10, 12, 0.88) 0%, rgba(10, 10, 12, 0.64) 34%, rgba(10, 10, 12, 0.18) 72%)",
          }}
        >
          {label && (
            <div
              className="border border-bristol/18 px-4 py-2 font-display text-[clamp(1rem,8vw,1.45rem)] font-bold leading-none shadow-ink-sm"
              style={{ backgroundColor: "rgba(10, 10, 12, 0.76)", color: LABEL_COLOR }}
            >
              {label}
            </div>
          )}
          {caption && (
            <div className="mt-2 bg-ink-black/56 px-2 py-1 font-meta text-[0.5rem] tracking-[0.18em] text-bristol/82">
              {caption}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

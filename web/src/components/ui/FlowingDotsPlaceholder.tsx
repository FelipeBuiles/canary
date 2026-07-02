import type { CSSProperties, ReactNode } from "react";
import { useEffect, useRef } from "react";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";

interface FlowingDotsPlaceholderProps {
  aspect?: string;
  className?: string;
  label?: ReactNode;
  caption?: ReactNode;
  /** Small contexts (e.g. 84px state tiles): shrink the label and drop the
   *  oversized badge/caption so it fits instead of overflowing the tile. */
  compact?: boolean;
  "aria-label"?: string;
}

export function FlowingDotsPlaceholder({
  aspect = "4 / 5",
  className,
  label,
  caption,
  compact = false,
  "aria-label": ariaLabel = "Image generation in progress",
}: FlowingDotsPlaceholderProps) {
  const { t } = useI18n();
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const rafRef = useRef<number | null>(null);
  const startRef = useRef<number>(0);

  const displayLabel = label ?? t("DRAWING…");
  const displayCaption = caption ? t(String(caption)) : undefined;

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

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(wrap);

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const draw = (now: number) => {
      if (!startRef.current) startRef.current = now;
      // Seconds since start; frozen at a representative frame when the user
      // prefers reduced motion.
      const elapsed = reducedMotion ? 0.6 : (now - startRef.current) / 1000;

      // 1. Pulp-paper ground
      ctx.fillStyle = "#fcfaed";
      ctx.fillRect(0, 0, width, height);

      // 2. Gold "develop" band — a soft narrator-gold glow drifting slowly
      //    down and back up the page, like ink developing line by line.
      const sweep = 0.5 + 0.62 * Math.sin(elapsed * 0.5); // normalized Y center
      const c = Math.max(0, Math.min(1, sweep));
      const band = ctx.createLinearGradient(0, 0, 0, height);
      band.addColorStop(Math.max(0, c - 0.35), "rgba(250, 227, 97, 0)");
      band.addColorStop(c, "rgba(250, 227, 97, 0.18)");
      band.addColorStop(Math.min(1, c + 0.35), "rgba(250, 227, 97, 0)");
      ctx.fillStyle = band;
      ctx.fillRect(0, 0, width, height);

      // 3. Benday halftone dots — ink-black, swelling and darkening as the
      //    gold band crosses them. glow/radius/alpha depend only on the row,
      //    so they are hoisted out of the inner loop; the micro-pulse adds a
      //    faint per-cell shimmer.
      const cellSize = 12;
      const baseRadius = 1.5;
      for (let py = cellSize * 0.5; py < height; py += cellSize) {
        const ny = py / Math.max(height, 1);
        const glow = Math.max(0, 1 - Math.abs(ny - sweep) / 0.22);
        const radius = baseRadius * (1 + glow * 0.6);
        const alpha = 0.07 + glow * 0.18;
        for (let px = cellSize * 0.5; px < width; px += cellSize) {
          const pulse = 0.92 + 0.08 * Math.sin(elapsed * 1.6 + (px + py) * 0.05);
          ctx.beginPath();
          ctx.fillStyle = `rgba(27, 28, 21, ${alpha})`;
          ctx.arc(px, py, radius * pulse, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // 4. Thick tactile neobrutalist border
      ctx.strokeStyle = "#1b1c15";
      ctx.lineWidth = 4;
      ctx.strokeRect(0, 0, width, height);

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
      className={cn("relative w-full overflow-hidden border-[2px] border-ink-black bg-pulp-paper", className)}
      style={style}
    >
      <canvas
        ref={canvasRef}
        aria-hidden="true"
        className="block h-full w-full"
      />
      {(displayLabel || displayCaption) && (
        <div
          className={cn(
            "absolute inset-0 flex flex-col items-center justify-center text-center pointer-events-none",
            compact ? "px-1" : "px-4",
          )}
        >
          {displayLabel && (
            <div
              className={cn(
                "border-ink-black bg-bristol text-ink-black font-display font-black uppercase leading-none",
                compact
                  ? "border-[2px] px-1.5 py-1 text-[0.5rem] tracking-[0.08em]"
                  : "border-[3px] px-5 py-2.5 text-[clamp(1rem,8vw,1.38rem)] shadow-ink tracking-tight",
              )}
            >
              {displayLabel}
            </div>
          )}
          {displayCaption && !compact && (
            <div className="mt-3.5 border-[2px] border-ink-black bg-pulp-paper px-3 py-1 font-meta text-[0.62rem] font-bold tracking-[0.16em] text-ink-black shadow-paper-sm uppercase">
              {displayCaption}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

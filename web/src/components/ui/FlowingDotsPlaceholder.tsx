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
    if (!canvas || !wrap) return;
    const rawContext = canvas.getContext("2d");
    if (!rawContext) return;
    const context: CanvasRenderingContext2D = rawContext;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let width = 0;
    let height = 0;
    let visible = true;
    const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
    let reducedMotion = motionPreference.matches;

    const resize = () => {
      const rect = wrap.getBoundingClientRect();
      width = rect.width;
      height = rect.height;
      canvas.width = Math.max(1, Math.floor(width * dpr));
      canvas.height = Math.max(1, Math.floor(height * dpr));
      context.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    resize();
    const observer = new ResizeObserver(() => {
      resize();
      if (reducedMotion) draw(performance.now());
    });
    observer.observe(wrap);

    function requestDraw() {
      if (rafRef.current == null && visible) {
        rafRef.current = requestAnimationFrame(draw);
      }
    }

    function draw(now: number) {
      rafRef.current = null;
      if (!startRef.current) startRef.current = now;
      // Seconds since start; frozen at a representative frame when the user
      // prefers reduced motion.
      const elapsed = reducedMotion ? 0.6 : (now - startRef.current) / 1000;

      // 1. Pulp-paper ground
      context.fillStyle = "#fcfaed";
      context.fillRect(0, 0, width, height);

      // 2. Gold develop band — a single mechanical ink pass moving down and
      //    back up the page, like a proof traveling through the press.
      const sweep = 0.5 + 0.62 * Math.sin(elapsed * 0.5); // normalized Y center
      const c = Math.max(0, Math.min(1, sweep));
      const band = context.createLinearGradient(0, 0, 0, height);
      band.addColorStop(Math.max(0, c - 0.35), "rgba(250, 227, 97, 0)");
      band.addColorStop(c, "rgba(250, 227, 97, 0.18)");
      band.addColorStop(Math.min(1, c + 0.35), "rgba(250, 227, 97, 0)");
      context.fillStyle = band;
      context.fillRect(0, 0, width, height);

      // 3. Benday halftone dots — ink-black, registering as the pass reaches
      //    each row. The dots stay still; only the meaningful press pass moves.
      const cellSize = 12;
      const baseRadius = 1.5;
      for (let py = cellSize * 0.5; py < height; py += cellSize) {
        const ny = py / Math.max(height, 1);
        const glow = Math.max(0, 1 - Math.abs(ny - sweep) / 0.22);
        const radius = baseRadius * (1 + glow * 0.6);
        const alpha = 0.07 + glow * 0.18;
        for (let px = cellSize * 0.5; px < width; px += cellSize) {
          context.beginPath();
          context.fillStyle = `rgba(27, 28, 21, ${alpha})`;
          context.arc(px, py, radius, 0, Math.PI * 2);
          context.fill();
        }
      }

      // 4. Thick tactile neobrutalist border
      context.strokeStyle = "#1b1c15";
      context.lineWidth = 4;
      context.strokeRect(0, 0, width, height);

      if (!reducedMotion) requestDraw();
    }

    const visibilityObserver = "IntersectionObserver" in window
      ? new IntersectionObserver(([entry]) => {
          visible = entry?.isIntersecting ?? true;
          if (visible && !reducedMotion) requestDraw();
          else if (rafRef.current != null) {
            cancelAnimationFrame(rafRef.current);
            rafRef.current = null;
          }
        })
      : null;
    visibilityObserver?.observe(wrap);

    function onMotionChange(event: MediaQueryListEvent) {
      reducedMotion = event.matches;
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      if (reducedMotion) draw(performance.now());
      else requestDraw();
    }
    motionPreference.addEventListener("change", onMotionChange);
    if (reducedMotion) draw(performance.now());
    else requestDraw();

    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      motionPreference.removeEventListener("change", onMotionChange);
      observer.disconnect();
      visibilityObserver?.disconnect();
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
                  ? "max-w-full break-words border-[2px] px-1 py-1 text-xs tracking-normal"
                  : "border-[3px] px-5 py-2.5 text-[clamp(1rem,8vw,1.38rem)] shadow-ink tracking-[-0.03em]",
              )}
            >
              {displayLabel}
            </div>
          )}
          {displayCaption && !compact && (
            <div className="mt-3.5 border-[2px] border-ink-black bg-pulp-paper px-3 py-1 font-meta text-xs font-bold tracking-[0.08em] text-ink-black shadow-paper-sm uppercase">
              {displayCaption}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

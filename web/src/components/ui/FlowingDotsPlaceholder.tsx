import type { CSSProperties, ReactNode } from "react";
import { useEffect, useRef } from "react";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";

interface FlowingDotsPlaceholderProps {
  aspect?: string;
  className?: string;
  label?: ReactNode;
  caption?: ReactNode;
  "aria-label"?: string;
}

export function FlowingDotsPlaceholder({
  aspect = "4 / 5",
  className,
  label,
  caption,
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
      const t = reducedMotion ? 0 : ((now - startRef.current) / 1000) * 1.8;

      // 1. Fondo de papel pulpa
      ctx.fillStyle = "#fcfaed";
      ctx.fillRect(0, 0, width, height);

      // 2. Líneas de boceto azul cián (Non-photo blue)
      ctx.strokeStyle = "rgba(44, 150, 219, 0.12)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      // Regla de tercios
      ctx.moveTo(width / 3, 0); ctx.lineTo(width / 3, height);
      ctx.moveTo((2 * width) / 3, 0); ctx.lineTo((2 * width) / 3, height);
      ctx.moveTo(0, height / 3); ctx.lineTo(width, height / 3);
      ctx.moveTo(0, (2 * height) / 3); ctx.lineTo(width, (2 * height) / 3);
      // Diagonales de composición
      ctx.moveTo(0, 0); ctx.lineTo(width, height);
      ctx.moveTo(width, 0); ctx.lineTo(0, height);
      ctx.stroke();

      // 3. Onda de escáner dorada (Onda de Revelado) - Muy suave y lenta
      const sweepCenter = 0.5 + 0.75 * Math.sin(t * 0.22);
      
      const grad = ctx.createLinearGradient(0, 0, width, height);
      const c = Math.max(0, Math.min(1, sweepCenter));
      
      grad.addColorStop(Math.max(0, c - 0.4), "rgba(250, 227, 97, 0)");
      grad.addColorStop(Math.max(0, c - 0.15), "rgba(250, 227, 97, 0.05)");
      grad.addColorStop(c, "rgba(250, 227, 97, 0.16)");
      grad.addColorStop(Math.min(1, c + 0.15), "rgba(250, 227, 97, 0.05)");
      grad.addColorStop(Math.min(1, c + 0.4), "rgba(250, 227, 97, 0)");
      
      ctx.fillStyle = grad;
      ctx.fillRect(0, 0, width, height);

      // 4. Trama de puntos Benday Halftone - Pulsación suave en escala de grises
      const cellSize = 14;
      const cols = Math.ceil(width / cellSize);
      const rows = Math.ceil(height / cellSize);
      const baseRadius = 1.8;

      for (let row = 0; row < rows; row++) {
        for (let col = 0; col < cols; col++) {
          const px = col * cellSize + cellSize * 0.5;
          const py = row * cellSize + cellSize * 0.5;
          const nx = px / Math.max(width, 1);
          const ny = py / Math.max(height, 1);
          const cellDiag = (nx + ny) / 2;

          const distToSweep = cellDiag - sweepCenter;
          const sweepGlow = Math.max(0, 1 - Math.abs(distToSweep) / 0.25);

          let radius = baseRadius;
          const rgb = [27, 28, 21]; // Mantener siempre tinta negra
          let alpha = 0.06;

          if (sweepGlow > 0) {
            // Crecimiento y oscurecimiento muy suaves y progresivos
            radius = baseRadius * (1.0 + sweepGlow * 0.35);
            alpha = 0.06 + sweepGlow * 0.16;
          }

          // Micro-pulso individual por celda para dar textura orgánica
          const pulse = 0.9 + 0.1 * Math.sin(t * 1.8 + (col + row) * 0.25);

          ctx.beginPath();
          ctx.fillStyle = `rgba(${rgb[0]}, ${rgb[1]}, ${rgb[2]}, ${alpha})`;
          ctx.arc(px, py, radius * pulse, 0, Math.PI * 2);
          ctx.fill();
        }
      }

      // 5. Borde grueso táctil neobrutalista
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
          className="absolute inset-0 flex flex-col items-center justify-center px-4 text-center pointer-events-none"
        >
          {displayLabel && (
            <div
              className="border-[3px] border-ink-black px-5 py-2.5 font-display text-[clamp(1rem,8vw,1.38rem)] font-black leading-none shadow-ink bg-bristol text-ink-black uppercase tracking-tight"
            >
              {displayLabel}
            </div>
          )}
          {displayCaption && (
            <div className="mt-3.5 border-[2px] border-ink-black bg-pulp-paper px-3 py-1 font-meta text-[0.62rem] font-bold tracking-[0.16em] text-ink-black shadow-paper-sm uppercase">
              {displayCaption}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

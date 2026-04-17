import { useCallback, useEffect, useRef, useState } from "react";
import { computeScale } from "./coordinates";

interface ScaledContainerProps {
  children: React.ReactNode;
  onScaleChange?: (scale: number) => void;
}

/**
 * Renders children at 2480x3508 native size, scaled to fit the viewport
 * via CSS transform. Uses ResizeObserver to track container size.
 */
export function ScaledContainer({ children, onScaleChange }: ScaledContainerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0);

  const compute = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    const s = computeScale(el.clientWidth, el.clientHeight);
    setScale(s);
    onScaleChange?.(s);
  }, [onScaleChange]);

  useEffect(() => {
    compute();
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    return () => ro.disconnect();
  }, [compute]);

  if (scale === 0) {
    return <div ref={containerRef} className="w-full h-full" />;
  }

  return (
    <div ref={containerRef} className="w-full h-full flex items-center justify-center overflow-hidden">
      <div
        style={{
          width: Math.round(2480 * scale),
          height: Math.round(3508 * scale),
          flexShrink: 0,
          position: "relative",
        }}
      >
        <div
          style={{
            width: 2480,
            height: 3508,
            transform: `scale(${scale})`,
            transformOrigin: "top left",
            position: "absolute",
            top: 0,
            left: 0,
          }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}

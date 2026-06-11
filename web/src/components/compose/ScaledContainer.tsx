import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { computeScale } from "./coordinates";
import { PAGE_W, PAGE_H } from "./layouts";

interface ScaledContainerProps {
  children: React.ReactNode;
  zoom?: number;
  onZoomChange?: (zoom: number) => void;
  onScaleChange?: (scale: number) => void;
  /** Native content size — defaults to a single comic page. */
  nativeW?: number;
  nativeH?: number;
  maxZoom?: number;
  /** Inner padding (px) reserved around the content when computing fit. */
  fitPadding?: number;
}

/**
 * Renders children at native size (default 2480x3508), scaled to fit the
 * viewport via CSS transform. Uses ResizeObserver to track container size.
 * Handles wheel-zoom around the cursor and drag-panning when zoomed in.
 */
export function ScaledContainer({
  children,
  zoom = 1,
  onZoomChange,
  onScaleChange,
  nativeW = PAGE_W,
  nativeH = PAGE_H,
  maxZoom = 2.5,
  fitPadding = 0,
}: ScaledContainerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [fitScale, setFitScale] = useState(0);
  const panRef = useRef<{ startX: number; startY: number; left: number; top: number } | null>(null);
  const pendingScrollRef = useRef<{ left: number; top: number } | null>(null);

  const compute = useCallback(() => {
    const el = containerRef.current;
    if (!el) return;
    setFitScale(computeScale(el.clientWidth - fitPadding, el.clientHeight - fitPadding, nativeW, nativeH));
  }, [nativeW, nativeH, fitPadding]);

  useEffect(() => {
    compute();
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    return () => ro.disconnect();
  }, [compute]);

  const scale = fitScale * zoom;

  useEffect(() => {
    onScaleChange?.(scale);
  }, [onScaleChange, scale]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !onZoomChange || fitScale <= 0) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();

      const zoomFactor = e.deltaY < 0 ? 1.1 : 0.9;
      const nextZoom = Math.max(0.5, Math.min(maxZoom, Number((zoom * zoomFactor).toFixed(3))));
      if (nextZoom === zoom) return;

      const rect = el.getBoundingClientRect();
      const xInContent = e.clientX - rect.left + el.scrollLeft;
      const yInContent = e.clientY - rect.top + el.scrollTop;
      const ratio = nextZoom / zoom;
      const nextLeft = xInContent * ratio - (e.clientX - rect.left);
      const nextTop = yInContent * ratio - (e.clientY - rect.top);

      pendingScrollRef.current = { left: nextLeft, top: nextTop };
      onZoomChange(nextZoom);
    };

    el.addEventListener("wheel", handleWheel, { passive: false });
    return () => el.removeEventListener("wheel", handleWheel);
  }, [fitScale, onZoomChange, zoom, maxZoom]);

  useLayoutEffect(() => {
    const el = containerRef.current;
    const scroll = pendingScrollRef.current;
    if (!el || !scroll) return;
    pendingScrollRef.current = null;
    el.scrollLeft = scroll.left;
    el.scrollTop = scroll.top;
  }, [zoom]);

  if (scale === 0) {
    return <div ref={containerRef} className="w-full h-full" />;
  }

  function handleMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    if (zoom <= 1 || e.button !== 0) return;
    const target = e.target as HTMLElement;
    if (target.closest("[data-editor-selectable]")) return;
    const el = containerRef.current;
    if (!el) return;
    panRef.current = {
      startX: e.clientX,
      startY: e.clientY,
      left: el.scrollLeft,
      top: el.scrollTop,
    };
    el.style.cursor = "grabbing";
    e.preventDefault();
  }

  function handleMouseMove(e: React.MouseEvent<HTMLDivElement>) {
    const pan = panRef.current;
    const el = containerRef.current;
    if (!pan || !el) return;
    el.scrollLeft = pan.left - (e.clientX - pan.startX);
    el.scrollTop = pan.top - (e.clientY - pan.startY);
  }

  function stopPan() {
    panRef.current = null;
    const el = containerRef.current;
    if (el) {
      el.style.cursor = zoom > 1 ? "grab" : "default";
    }
  }

  return (
    <div
      ref={containerRef}
      className="w-full h-full overflow-auto"
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={stopPan}
      onMouseLeave={stopPan}
      style={{ cursor: zoom > 1 ? "grab" : "default" }}
    >
      <div
        style={{
          width: Math.round(nativeW * scale),
          height: Math.round(nativeH * scale),
          margin: "auto",
          position: "relative",
        }}
      >
        <div
          style={{
            width: nativeW,
            height: nativeH,
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

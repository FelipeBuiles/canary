import { useEffect, useEffectEvent, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent, type PointerEvent, type ReactNode, type SyntheticEvent } from "react";
import { ChevronLeft, ChevronRight, Download } from "lucide-react";
import { useDialogFocus } from "../../hooks/useDialogFocus";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import {
  ZOOM_STEP, centeredView, clampView, fitScale, scaleLimits, visibleRegion, zoomAt,
  type Point, type Size, type ZoomView,
} from "../../lib/zoomPan";
import { Icon } from "./Icon";

export interface ViewerImage {
  src: string;
  alt: string;
  /** Heading in the viewer; defaults to the alt text. */
  label?: string;
  /** False hides the download control, e.g. in blind comparisons. */
  downloadable?: boolean;
}

const CHROME_BUTTON = "flex h-11 min-w-11 shrink-0 items-center justify-center border-[2px] border-bristol/40 px-3 font-meta text-xs font-bold tracking-[0.08em] text-bristol transition-colors hover:border-bristol disabled:pointer-events-none disabled:opacity-35 aria-pressed:border-narrator-gold aria-pressed:text-narrator-gold focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-narrator-gold";

function ChromeButton({ label, className, children, ...props }: { label: string; children: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button type="button" aria-label={label} title={label} className={cn(CHROME_BUTTON, className)} {...props}>{children}</button>;
}

type Gesture =
  | { kind: "pan"; origin: Point; view: ZoomView; zoomed: boolean; moved: boolean; at: number }
  | { kind: "pinch"; distance: number; mid: Point; view: ZoomView };

const distance = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y) || 1;
const midpoint = (a: Point, b: Point) => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
/** Keep viewer gestures and keys from reaching the React ancestors that opened it. */
const contain = (event: SyntheticEvent) => event.stopPropagation();

export function ImageViewer({ images, index, onIndexChange, onClose }: {
  images: ViewerImage[];
  index: number;
  onIndexChange: (index: number) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const dialogRef = useRef<HTMLDivElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  useDialogFocus(dialogRef, { onClose, initialFocusRef: stageRef });

  const image = images[Math.min(index, images.length - 1)];
  const many = images.length > 1;
  const title = image.label ?? image.alt;

  const [stage, setStage] = useState<Size>({ width: 0, height: 0 });
  const [loaded, setLoaded] = useState<{ src: string; size: Size } | null>(null);
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const [zoom, setZoom] = useState<{ src: string; view: ZoomView } | null>(null);
  const [animated, setAnimated] = useState(false);

  // Derived per source, so switching images resets to fit without remounting the stage.
  const natural = loaded?.src === image.src ? loaded.size : null;
  const failed = failedSrc === image.src;
  const ready = !!natural && stage.width > 0;
  const fit = ready ? fitScale(natural, stage) : 1;
  const limits = scaleLimits(fit);
  const explicit = ready && zoom?.src === image.src ? clampView(zoom.view, natural, stage) : null;
  const view = ready ? explicit ?? centeredView(fit, natural, stage) : null;
  const zoomed = !!explicit;

  useLayoutEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const measure = () => {
      const { width, height } = element.getBoundingClientRect();
      setStage((current) => current.width === width && current.height === height ? current : { width, height });
    };
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  /** Back to fit whenever a change lands on the fitted scale. */
  const commit = (next: ZoomView | null, animate = false) => {
    setAnimated(animate);
    setZoom(next && Math.abs(next.scale - fit) > fit * 0.001 ? { src: image.src, view: next } : null);
  };
  const center = (): Point => ({ x: stage.width / 2, y: stage.height / 2 });
  const zoomTo = (scale: number, anchor: Point = center(), animate = false) => {
    if (view && natural) commit(zoomAt(view, scale, anchor, natural, stage), animate);
  };
  const pan = (dx: number, dy: number) => {
    if (view && natural && zoomed) commit(clampView({ ...view, x: view.x + dx, y: view.y + dy }, natural, stage), true);
  };
  const toggle = (anchor: Point) => zoomed ? commit(null, true) : zoomTo(Math.max(1, fit * 2), anchor, true);
  const go = (step: number) => {
    setAnimated(false);
    onIndexChange((index + step + images.length) % images.length);
  };

  const pointAt = (event: { clientX: number; clientY: number }): Point => {
    const rect = stageRef.current?.getBoundingClientRect();
    return { x: event.clientX - (rect?.left ?? 0), y: event.clientY - (rect?.top ?? 0) };
  };

  // Wheel and Safari's trackpad gestures must be non-passive to keep the page from zooming.
  const gestureStart = useRef(1);
  const onWheel = useEffectEvent((event: WheelEvent) => {
    event.preventDefault();
    if (!view) return;
    const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? stage.height : 1;
    zoomTo(view.scale * Math.exp(-event.deltaY * unit * (event.ctrlKey ? 0.01 : 0.002)), pointAt(event));
  });
  const onGesture = useEffectEvent((event: Event & { scale?: number; clientX?: number; clientY?: number }) => {
    event.preventDefault();
    if (!view) return;
    if (event.type === "gesturestart") gestureStart.current = view.scale;
    else zoomTo(gestureStart.current * (event.scale ?? 1), pointAt({ clientX: event.clientX ?? 0, clientY: event.clientY ?? 0 }));
  });
  useEffect(() => {
    const element = stageRef.current;
    if (!element) return;
    const wheel = (event: WheelEvent) => onWheel(event);
    const gesture = (event: Event) => onGesture(event);
    element.addEventListener("wheel", wheel, { passive: false });
    element.addEventListener("gesturestart", gesture);
    element.addEventListener("gesturechange", gesture);
    return () => {
      element.removeEventListener("wheel", wheel);
      element.removeEventListener("gesturestart", gesture);
      element.removeEventListener("gesturechange", gesture);
    };
  }, []);

  const pointers = useRef(new Map<number, Point>());
  const gesture = useRef<Gesture | null>(null);
  const lastTap = useRef<{ at: number; point: Point } | null>(null);
  const beginGesture = () => {
    const points = [...pointers.current.values()];
    if (!view || !points.length) gesture.current = null;
    else if (points.length >= 2) gesture.current = { kind: "pinch", distance: distance(points[0], points[1]), mid: midpoint(points[0], points[1]), view };
    else gesture.current = { kind: "pan", origin: points[0], view, zoomed, moved: false, at: performance.now() };
  };
  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.pointerType === "mouse" && event.button !== 0) return;
    event.currentTarget.setPointerCapture?.(event.pointerId);
    pointers.current.set(event.pointerId, pointAt(event));
    setAnimated(false);
    beginGesture();
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!pointers.current.has(event.pointerId)) return;
    const point = pointAt(event);
    pointers.current.set(event.pointerId, point);
    const active = gesture.current;
    if (!active || !natural) return;
    if (active.kind === "pan") {
      const dx = point.x - active.origin.x, dy = point.y - active.origin.y;
      if (Math.hypot(dx, dy) > 6) active.moved = true;
      if (active.zoomed) commit(clampView({ ...active.view, x: active.view.x + dx, y: active.view.y + dy }, natural, stage));
      return;
    }
    const [a, b] = [...pointers.current.values()];
    if (!a || !b) return;
    const mid = midpoint(a, b);
    const scaled = zoomAt(active.view, active.view.scale * distance(a, b) / active.distance, active.mid, natural, stage);
    commit(clampView({ ...scaled, x: scaled.x + mid.x - active.mid.x, y: scaled.y + mid.y - active.mid.y }, natural, stage));
  };
  const endPointer = (event: PointerEvent<HTMLDivElement>, cancelled: boolean) => {
    if (!pointers.current.delete(event.pointerId)) return;
    const active = gesture.current;
    if (!cancelled && active?.kind === "pan" && pointers.current.size === 0) {
      const point = pointAt(event);
      const dx = point.x - active.origin.x, dy = point.y - active.origin.y;
      if (!active.moved && performance.now() - active.at < 300) {
        const previous = lastTap.current;
        if (previous && performance.now() - previous.at < 320 && distance(previous.point, point) < 30) {
          lastTap.current = null;
          toggle(point);
        } else lastTap.current = { at: performance.now(), point };
      } else if (!active.zoomed && many && Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.2) {
        go(dx < 0 ? 1 : -1);
      }
    }
    beginGesture();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    // The dialog lifecycle needs Escape and Tab on window; nothing else may reach the opener.
    if (event.key !== "Escape" && event.key !== "Tab") event.stopPropagation();
    if (event.altKey || event.ctrlKey || event.metaKey || !view) return;
    const target = event.target as HTMLElement;
    if ((event.key === "Enter" || event.key === " ") && target.closest("button, a")) return;
    const step = Math.max(stage.width, stage.height) * 0.15;
    switch (event.key) {
      case "+": case "=": zoomTo(view.scale * ZOOM_STEP, undefined, true); break;
      case "-": case "_": zoomTo(view.scale / ZOOM_STEP, undefined, true); break;
      case "0": commit(null, true); break;
      case "1": zoomTo(1, undefined, true); break;
      case "ArrowLeft": if (zoomed) pan(step, 0); else if (many) go(-1); else return; break;
      case "ArrowRight": if (zoomed) pan(-step, 0); else if (many) go(1); else return; break;
      case "ArrowUp": if (zoomed) pan(0, step); else return; break;
      case "ArrowDown": if (zoomed) pan(0, -step); else return; break;
      default: return;
    }
    event.preventDefault();
  };

  // The navigator recenters the close-up wherever it is pressed or dragged.
  const navigate = (event: PointerEvent<HTMLDivElement>) => {
    if (!view || !natural || (event.type === "pointermove" && !event.currentTarget.hasPointerCapture?.(event.pointerId))) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const fx = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    const fy = Math.min(1, Math.max(0, (event.clientY - rect.top) / rect.height));
    commit(clampView({
      ...view,
      x: stage.width / 2 - fx * natural.width * view.scale,
      y: stage.height / 2 - fy * natural.height * view.scale,
    }, natural, stage));
  };
  const region = view && natural && zoomed ? visibleRegion(view, natural, stage) : null;

  const percent = view ? Math.round(view.scale * 100) : null;
  const atActual = !!view && Math.abs(view.scale - 1) < 0.005;
  const canDownload = image.downloadable !== false;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={`${t("Image viewer")} · ${title}`}
      className="fixed inset-0 z-[150] flex flex-col bg-ink-black text-bristol"
      onKeyDown={onKeyDown}
      onClick={contain}
      onDoubleClick={contain}
      onPointerDown={contain}
      onPointerMove={contain}
      onPointerUp={contain}
      onMouseDown={contain}
      onTouchStart={contain}
      onTouchEnd={contain}
    >
      <header className="flex shrink-0 items-center gap-3 border-b-[2px] border-bristol/25 px-3 py-2 md:px-5 md:py-3">
        <div className="min-w-0 flex-1">
          <p className="truncate font-display text-lg font-black uppercase leading-tight">{title}</p>
          {many && <p className="font-meta text-xs font-bold tracking-[0.12em] text-bristol/60" aria-live="polite">{index + 1} / {images.length}</p>}
        </div>
        <p className="hidden max-w-sm text-right font-meta text-xs leading-5 text-bristol/60 lg:block">
          {t("Scroll or pinch to zoom · Drag to move · Double-click to toggle")}
        </p>
        {canDownload && (
          <a href={image.src} download aria-label={t("Download image")} title={t("Download image")} className={CHROME_BUTTON}>
            <Download size={14} aria-hidden="true" />
          </a>
        )}
        <ChromeButton label={t("Close")} onClick={onClose}><Icon name="x" size={14} /></ChromeButton>
      </header>

      <div className="relative min-h-0 flex-1">
        <div
          ref={stageRef}
          tabIndex={0}
          role="group"
          aria-roledescription={t("zoomable image")}
          aria-label={image.alt}
          aria-describedby="image-viewer-keys"
          data-testid="image-viewer-stage"
          className={cn(
            "absolute inset-0 touch-none select-none overflow-hidden focus-visible:outline-[3px] focus-visible:-outline-offset-[3px] focus-visible:outline-narrator-gold",
            zoomed ? "cursor-grab active:cursor-grabbing" : "cursor-zoom-in",
          )}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={(event) => endPointer(event, false)}
          onPointerCancel={(event) => endPointer(event, true)}
        >
          {!failed && (
            <img
              key={image.src}
              src={image.src}
              alt={image.alt}
              draggable={false}
              decoding="async"
              onLoad={(event) => setLoaded({
                src: image.src,
                size: { width: event.currentTarget.naturalWidth || 1, height: event.currentTarget.naturalHeight || 1 },
              })}
              onError={() => setFailedSrc(image.src)}
              className={cn(
                "absolute left-0 top-0 max-w-none origin-top-left select-none",
                animated && "transition-transform duration-[var(--motion-settle)] ease-[var(--ease-press)] motion-reduce:transition-none",
                !view && "invisible",
              )}
              style={view && natural ? {
                width: natural.width,
                height: natural.height,
                transform: `translate3d(${view.x}px, ${view.y}px, 0) scale(${view.scale})`,
                // Past 2× the pixels are the subject; smoothing would invent detail.
                imageRendering: view.scale >= 2 ? "pixelated" : undefined,
              } : undefined}
            />
          )}
          {(failed || !view) && (
            <p role={failed ? "alert" : "status"} className="absolute inset-0 flex items-center justify-center px-6 text-center font-meta text-sm text-bristol/70">
              {failed ? t("The image could not be loaded.") : t("Loading image…")}
            </p>
          )}
        </div>
        <p id="image-viewer-keys" className="sr-only">
          {t("Use plus and minus to zoom, 0 to fit, 1 for actual size, and the arrow keys to move.")}
        </p>

        {many && <>
          <ChromeButton label={t("Previous image")} onClick={() => go(-1)} className="absolute left-3 top-1/2 -translate-y-1/2 bg-ink-black/70 px-0">
            <ChevronLeft size={18} aria-hidden="true" />
          </ChromeButton>
          <ChromeButton label={t("Next image")} onClick={() => go(1)} className="absolute right-3 top-1/2 -translate-y-1/2 bg-ink-black/70 px-0">
            <ChevronRight size={18} aria-hidden="true" />
          </ChromeButton>
          {[...new Set([images[(index + 1) % images.length].src, images[(index - 1 + images.length) % images.length].src])].map((src) => (
            <link key={src} rel="preload" as="image" href={src} />
          ))}
        </>}

        {region && natural && (
          <div
            aria-hidden="true"
            data-testid="image-viewer-navigator"
            className="absolute bottom-3 right-3 hidden w-28 cursor-crosshair touch-none border-[2px] border-bristol/60 bg-ink-black md:block lg:w-36"
            style={{ aspectRatio: `${natural.width} / ${natural.height}`, maxHeight: "40%" }}
            onPointerDown={(event) => { event.currentTarget.setPointerCapture?.(event.pointerId); navigate(event); }}
            onPointerMove={navigate}
          >
            <img src={image.src} alt="" draggable={false} className="pointer-events-none h-full w-full object-contain opacity-70" />
            <span
              className="pointer-events-none absolute border-[2px] border-narrator-gold"
              style={{
                left: `${region.left * 100}%`, top: `${region.top * 100}%`,
                width: `${region.width * 100}%`, height: `${region.height * 100}%`,
              }}
            />
          </div>
        )}
      </div>

      <footer className="flex shrink-0 justify-center border-t-[2px] border-bristol/25 px-3 py-2 md:py-3">
        <div role="toolbar" aria-label={t("Zoom controls")} className="flex items-center gap-2">
          <ChromeButton label={t("Zoom out")} disabled={!view || view.scale <= limits.min * 1.001} onClick={() => view && zoomTo(view.scale / ZOOM_STEP, undefined, true)} className="px-0">
            <Icon name="zoom-out" size={16} />
          </ChromeButton>
          <output aria-label={t("Zoom level")} className="min-w-14 text-center font-meta text-xs font-bold tabular-nums">
            {percent == null ? "—" : `${percent}%`}
          </output>
          <ChromeButton label={t("Zoom in")} disabled={!view || view.scale >= limits.max * 0.999} onClick={() => view && zoomTo(view.scale * ZOOM_STEP, undefined, true)} className="px-0">
            <Icon name="zoom-in" size={16} />
          </ChromeButton>
          <span aria-hidden="true" className="mx-1 h-6 w-[2px] bg-bristol/25" />
          <ChromeButton label={t("Fit to screen")} aria-pressed={!!view && !zoomed} disabled={!view} onClick={() => commit(null, true)}>
            {t("FIT")}
          </ChromeButton>
          <ChromeButton label={t("Actual size")} aria-pressed={atActual} disabled={!view} onClick={() => zoomTo(1, undefined, true)}>
            1:1
          </ChromeButton>
        </div>
      </footer>
    </div>
  );
}

import { useEffect, useEffectEvent, useRef, useState, type ReactNode } from "react";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";

const ZOOM = 2.5;
const SIZE = 180;

interface Lens {
  src: string;
  /** Pointer position within the wrapper. */
  x: number;
  y: number;
  /** Background geometry for the magnified image. */
  width: number;
  height: number;
  offsetX: number;
  offsetY: number;
  pixelated: boolean;
}

/** The drawn box of an `object-fit: contain` image, relative to its element. */
function contentBox(image: HTMLImageElement) {
  const rect = image.getBoundingClientRect();
  const natural = image.naturalWidth && image.naturalHeight
    ? image.naturalWidth / image.naturalHeight
    : rect.width / Math.max(rect.height, 1);
  const width = Math.min(rect.width, rect.height * natural);
  const height = width / natural;
  return {
    left: rect.left + (rect.width - width) / 2,
    top: rect.top + (rect.height - height) / 2,
    width,
    height,
  };
}

/**
 * Close inspection for art: hold Alt (Option) or press Z while pointing at the
 * image to show a 2.5× square loupe. Past 1:1 it switches to nearest-neighbor
 * so pixel art stays crisp instead of smearing.
 */
export function Loupe({ children, className }: { children: ReactNode; className?: string }) {
  const { t } = useI18n();
  const root = useRef<HTMLDivElement>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const [altHeld, setAltHeld] = useState(false);
  const [toggled, setToggled] = useState(false);
  const [lens, setLens] = useState<Lens | null>(null);
  const active = altHeld || toggled;

  const measure = () => {
    const wrapper = root.current;
    const image = wrapper?.querySelector("img");
    const at = pointer.current;
    if (!wrapper || !image || !at) return setLens(null);
    const box = contentBox(image);
    const within = at.x >= box.left && at.x <= box.left + box.width && at.y >= box.top && at.y <= box.top + box.height;
    if (!within || !box.width) return setLens(null);
    const origin = wrapper.getBoundingClientRect();
    const width = box.width * ZOOM, height = box.height * ZOOM;
    setLens({
      src: image.currentSrc || image.src,
      x: at.x - origin.left,
      y: at.y - origin.top,
      width,
      height,
      offsetX: SIZE / 2 - (at.x - box.left) * ZOOM,
      offsetY: SIZE / 2 - (at.y - box.top) * ZOOM,
      pixelated: image.naturalWidth > 0 && width > image.naturalWidth,
    });
  };

  const remeasure = useEffectEvent(measure);
  useEffect(() => {
    if (!active) return;
    const timer = window.setTimeout(remeasure, 0);
    return () => window.clearTimeout(timer);
  }, [active]);

  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      setAltHeld(event.altKey);
      if (event.type !== "keydown" || event.key.toLowerCase() !== "z" || !pointer.current) return;
      const target = event.target as HTMLElement | null;
      if (target?.closest("input, textarea, select, [contenteditable='true']")) return;
      setToggled((on) => !on);
    };
    const release = () => setAltHeld(false);
    window.addEventListener("keydown", keys);
    window.addEventListener("keyup", keys);
    window.addEventListener("blur", release);
    return () => {
      window.removeEventListener("keydown", keys);
      window.removeEventListener("keyup", keys);
      window.removeEventListener("blur", release);
    };
  }, []);

  return (
    <div
      ref={root}
      className={cn("relative", active && lens && "cursor-none", className)}
      title={t("Hold Alt or press Z to magnify")}
      onPointerMove={(event) => {
        pointer.current = { x: event.clientX, y: event.clientY };
        setAltHeld(event.altKey);
        if (active || event.altKey) measure();
      }}
      onPointerLeave={() => {
        pointer.current = null;
        setToggled(false);
        setLens(null);
      }}
    >
      {children}
      {active && lens && (
        <div
          aria-hidden="true"
          data-testid="loupe"
          className="pointer-events-none absolute z-20 border-[3px] border-ink-black bg-bristol shadow-ink-sm"
          style={{
            width: SIZE,
            height: SIZE,
            left: lens.x - SIZE / 2,
            top: lens.y - SIZE / 2,
            backgroundImage: `url("${lens.src.replace(/"/g, "%22")}")`,
            backgroundRepeat: "no-repeat",
            backgroundSize: `${lens.width}px ${lens.height}px`,
            backgroundPosition: `${lens.offsetX}px ${lens.offsetY}px`,
            imageRendering: lens.pixelated ? "pixelated" : "auto",
          }}
        />
      )}
    </div>
  );
}

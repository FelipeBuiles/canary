import { useEffect, useRef, useState, type PointerEvent } from "react";
import { useI18n } from "../../i18n";

const SEEN_PREFIX = "canary.revisionWipeSeen.";

function reducedMotion(): boolean {
  try {
    return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  } catch {
    return false;
  }
}

function takeFirstView(key: string): boolean {
  try {
    if (window.localStorage.getItem(SEEN_PREFIX + key) === "1") return false;
    window.localStorage.setItem(SEEN_PREFIX + key, "1");
    return true;
  } catch {
    return false;
  }
}

/**
 * Before/after wipe over two renders of the same page. The split is dragged on
 * the art or set with the slider. The first time a revision pair is shown, the
 * split sweeps once from before to after so the change reads at a glance.
 */
export function BeforeAfterWipe({
  beforeSrc,
  afterSrc,
  beforeAlt,
  afterAlt,
  beforeLabel,
  afterLabel,
  visible,
  firstViewKey,
}: {
  beforeSrc: string;
  afterSrc: string;
  beforeAlt: string;
  afterAlt: string;
  beforeLabel: string;
  afterLabel: string;
  /** False while the wipe sits in a closed disclosure; the sweep waits for it. */
  visible: boolean;
  firstViewKey: string;
}) {
  const { t } = useI18n();
  const [split, setSplit] = useState(50);
  const frame = useRef<number | null>(null);
  const dragging = useRef(false);

  useEffect(() => {
    if (!visible || reducedMotion() || !takeFirstView(firstViewKey)) return;
    const start = performance.now();
    const duration = 900;
    const step = (now: number) => {
      const progress = Math.min(1, (now - start) / duration);
      // Sweep before → after, then come to rest at the midpoint.
      const eased = 1 - Math.pow(1 - progress, 3);
      setSplit(progress < 1 ? 100 - eased * 100 : 50);
      frame.current = progress < 1 ? requestAnimationFrame(step) : null;
    };
    frame.current = requestAnimationFrame(step);
    return () => {
      if (frame.current != null) cancelAnimationFrame(frame.current);
      frame.current = null;
    };
  }, [visible, firstViewKey]);

  const follow = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (!rect.width) return;
    if (frame.current != null) {
      cancelAnimationFrame(frame.current);
      frame.current = null;
    }
    setSplit(Math.round(Math.min(100, Math.max(0, ((event.clientX - rect.left) / rect.width) * 100))));
  };

  return (
    <figure>
      <div
        data-testid="revision-wipe"
        className="relative cursor-ew-resize touch-none select-none"
        onPointerDown={(event) => {
          dragging.current = true;
          event.currentTarget.setPointerCapture(event.pointerId);
          follow(event);
        }}
        onPointerMove={(event) => { if (dragging.current) follow(event); }}
        onPointerUp={() => { dragging.current = false; }}
        onPointerCancel={() => { dragging.current = false; }}
      >
        <img src={afterSrc} alt={afterAlt} loading="lazy" decoding="async" draggable={false} className="block max-h-[70dvh] w-full object-contain" />
        <img
          src={beforeSrc}
          alt={beforeAlt}
          loading="lazy"
          decoding="async"
          draggable={false}
          className="absolute inset-0 h-full w-full object-contain"
          style={{ clipPath: `inset(0 ${100 - split}% 0 0)` }}
        />
        <div aria-hidden="true" className="pointer-events-none absolute inset-y-0 w-[3px] -translate-x-1/2 bg-ink-black" style={{ left: `${split}%` }}>
          <span className="absolute left-1/2 top-1/2 flex h-9 w-9 -translate-x-1/2 -translate-y-1/2 items-center justify-center border-[3px] border-ink-black bg-narrator-gold font-meta text-xs font-bold">⇆</span>
        </div>
        <span aria-hidden="true" className="pointer-events-none absolute left-2 top-2 bg-ink-black px-2 py-1 font-meta text-[0.65rem] font-bold text-bristol">{beforeLabel}</span>
        <span aria-hidden="true" className="pointer-events-none absolute right-2 top-2 bg-ink-black px-2 py-1 font-meta text-[0.65rem] font-bold text-bristol">{afterLabel}</span>
      </div>
      <label className="mt-3 flex items-center gap-3 font-meta text-xs font-bold text-ink-muted">
        {t("Before")}
        <input
          type="range"
          min={0}
          max={100}
          value={split}
          aria-label={t("Before and after split")}
          aria-valuetext={t("{before}% before, {after}% after", { before: String(split), after: String(100 - split) })}
          onChange={(event) => setSplit(Number(event.target.value))}
          className="h-11 flex-1 accent-hero-red"
        />
        {t("After")}
      </label>
    </figure>
  );
}

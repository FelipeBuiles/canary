import { useEffect, useLayoutEffect, useRef, useState, type AnimationEvent, type CSSProperties, type ReactNode } from "react";
import { usePipelineStore } from "../../store/pipeline";
import { splitProjectKey } from "../../api/projectScope";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { FlowingDotsPlaceholder } from "../ui/FlowingDotsPlaceholder";

interface Frame { src: string; index: number | null }
interface Frames { current: Frame | null; previous: Frame | null; entering: boolean }
/** showing → releasing (overlay fades over the card's own painted image) → released. */
type Phase = "showing" | "releasing" | "released";

const BLUR = [12, 6, 2, 0];
const blurOf = (frame: Frame) => frame.index === null ? 0 : BLUR[frame.index];
// Overscan proportional to blur, so soft edges never reveal the card behind.
const frameStyle = (frame: Frame) => ({ "--preview-blur": `${blurOf(frame)}px`, "--preview-scale": 1 + blurOf(frame) * 0.006 }) as CSSProperties;
const EMPTY: Frames = { current: null, previous: null, entering: false };
/** Longest the overlay waits for the card's own image before letting go. */
const RELEASE_WAIT_MS = 2500;
/** Longest finished pixels wait for a saved file the card has not been told about. */
const SETTLED_HOLD_MS = 10000;

/** How a decoded frame arrives: a press pass for drafts, a settle for the
 *  completed pixels, and a quiet crossfade to the saved file. */
function transition(frame: Frame): "develop" | "resolve" | "handoff" {
  if (frame.index === null) return "handoff";
  return frame.index >= 3 ? "resolve" : "develop";
}

/** Whether the card's own rendering of `src` is loaded and fully opaque, so
 *  removing the overlay cannot reveal a skeleton or a fade-in. */
function cardImageReady(container: HTMLElement, src: string, waitedMs: number): boolean {
  const wanted = new URL(src, window.location.href).href;
  const image = Array.from(container.querySelectorAll("img")).find((candidate) =>
    !candidate.closest("[data-preview-layer]") && !candidate.hasAttribute("data-preview-decoder")
    && (candidate.currentSrc === wanted || candidate.src === wanted));
  // A card that renders something else (a failure, a different URL) has
  // nothing to wait for beyond a frame.
  if (!image) return waitedMs > 100;
  return image.complete && image.naturalWidth > 0 && Number(getComputedStyle(image).opacity || 1) >= 0.99;
}

/** Hold the last decoded frame while the next preview or saved image loads. */
export function ImageGenerationPreview({ project, target, active, finalSrc, keepChildren = false, aspect, label, caption, className, children, "aria-label": ariaLabel }: {
  project: string;
  target: string;
  active: boolean;
  finalSrc?: string;
  /** While active, keep showing children (existing artwork) instead of the
   *  placeholder until a preview arrives — a redraw keeps its current page. */
  keepChildren?: boolean;
  aspect: string;
  label?: string;
  caption?: string;
  className?: string;
  children?: ReactNode;
  "aria-label"?: string;
}) {
  const { t } = useI18n();
  const stored = usePipelineStore((state) => {
    if (!state.projectId) return undefined;
    const current = splitProjectKey(state.projectId);
    const wanted = splitProjectKey(project);
    // Series assets follow the series stream from any part; pages stay part-scoped.
    if (current.id !== wanted.id || (target.startsWith("page:") && current.part !== wanted.part)) return undefined;
    return state.imagePreviews[target];
  });
  const releasePreview = usePipelineStore((state) => state.releaseImagePreview);
  const container = useRef<HTMLDivElement>(null);
  const [frames, setFrames] = useState<Frames>(EMPTY);
  const [phase, setPhase] = useState<Phase>("showing");
  // Finished pixels only continue a generation this card watched; a card that
  // mounts after the job ended renders its saved file as usual.
  const preview = stored?.settled && !frames.current ? undefined : stored;
  const settled = !!preview?.settled;
  // Saved cards retain their existing lazy image loading. Decode the saved URL
  // here only when handing off an actual generation preview.
  const src = active ? preview?.image_url : (frames.current?.index != null || frames.previous ? finalSrc : undefined);
  const index = active ? (preview?.preview_index ?? null) : null;
  const currentSrc = useRef(src);
  useLayoutEffect(() => { currentSrc.current = src; }, [src]);
  const showingPreview = frames.current?.index != null;
  // A finished job can report before the card learns it is idle or where its
  // saved file is; its completed pixels bridge that gap instead of the dots.
  const showArtwork = phase !== "released" && (
    (active && !!preview && showingPreview)
    || (!active && (!!finalSrc || settled) && (showingPreview || !!frames.previous || frames.current?.index === null)));
  // The first press pass reveals over the placeholder rather than a blank card.
  const placeholderVisible = !showArtwork || (frames.entering && !frames.previous);
  const kind = frames.current ? transition(frames.current) : null;
  const handedOff = !active && frames.current?.index === null && !frames.entering && phase === "showing";

  // Let go only once the card's own image is painted underneath.
  useEffect(() => {
    if (!handedOff || !finalSrc || !container.current) return;
    const element = container.current;
    const started = performance.now();
    let frame = 0;
    const tick = () => {
      const waited = performance.now() - started;
      if (cardImageReady(element, finalSrc, waited) || waited > RELEASE_WAIT_MS) setPhase("releasing");
      else frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [handedOff, finalSrc]);

  // Completed pixels never outlive a saved file that does not arrive.
  const waitingForSaved = !active && !finalSrc && showArtwork;
  useEffect(() => {
    if (!waitingForSaved) return;
    const timer = window.setTimeout(() => setPhase("releasing"), SETTLED_HOLD_MS);
    return () => window.clearTimeout(timer);
  }, [waitingForSaved]);

  const onLayerAnimationEnd = (event: AnimationEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget || phase !== "releasing") return;
    setPhase("released");
    setFrames(EMPTY);
    if (stored?.settled) releasePreview(target, stored.request_id);
  };

  return <div ref={container} className={cn("relative w-full overflow-hidden bg-surface-container", className)} style={{ aspectRatio: aspect }} aria-busy={active}>
    {active && !keepChildren
      ? placeholderVisible && <FlowingDotsPlaceholder aspect={aspect} className="h-full" label={label} caption={caption} aria-label={ariaLabel} />
      : children}
    {showArtwork && frames.current && <div data-preview-layer className={cn("pointer-events-none absolute inset-0 overflow-hidden", phase === "releasing" && "image-preview-release")}
      aria-hidden={!active} onAnimationEnd={onLayerAnimationEnd}>
      {frames.previous && <img src={frames.previous.src} alt="" aria-hidden="true" className="absolute h-full w-full object-contain"
        style={{ filter: `blur(${blurOf(frames.previous)}px)`, transform: `scale(${1 + blurOf(frames.previous) * 0.006})` }} />}
      <img key={`${frames.current.src}:${frames.current.index}`} src={frames.current.src} alt={active ? (ariaLabel ?? label ?? t("DRAWING…")) : ""}
        className={cn("image-focus-layer absolute h-full w-full object-contain", `image-focus-${kind}`)}
        style={frameStyle(frames.current)}
        onAnimationEnd={(event) => {
          event.stopPropagation();
          setFrames((current) => current.current?.src === frames.current?.src && current.current?.index === frames.current?.index
            ? { ...current, previous: null, entering: false } : current);
        }} />
      {kind === "develop" && <div key={`press:${frames.current.src}:${frames.current.index}`} aria-hidden="true" className="image-press-bar"
        onAnimationEnd={(event) => event.stopPropagation()} />}
      {active && !settled && <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-ink-black/80 to-transparent px-4 pb-4 pt-10">
        <span role="status" className="font-meta text-xs font-bold tracking-wide text-bristol">{label ?? t("DRAWING…")}</span>
      </div>}
    </div>}
    {src && <img key={`decode:${src}:${index}`} data-preview-decoder src={src} alt="" aria-hidden="true" className="absolute h-px w-px opacity-0" decoding="async"
      onLoad={() => {
        if (currentSrc.current !== src) return;
        setPhase("showing");
        setFrames((current) => current.current?.src === src && current.current.index === index ? current : {
          current: { src, index }, previous: current.current?.index != null ? current.current : null, entering: true,
        });
      }}
      onError={() => { if (!active && currentSrc.current === src) setFrames(EMPTY); }} />}
  </div>;
}

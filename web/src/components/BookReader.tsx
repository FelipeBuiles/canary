import { useEffect, useEffectEvent, useMemo, useRef, useState, type ReactNode } from "react";
import { pageCompositePreviewUrl } from "../api/lettering";
import { pageRenderPreviewUrl } from "../api/pages";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";
import { useDialogFocus } from "../hooks/useDialogFocus";
import { useImageViewer } from "../hooks/useImageViewer";
import {
  buildReaderViews,
  viewIndexForPage,
  viewLabel,
  type ReaderLayout,
  type ReaderPage,
  type ReaderView,
} from "../lib/bookReader";
import { Icon } from "./ui/Icon";
import { Skeleton } from "./ui/Skeleton";

type Fit = "height" | "width";

/**
 * How many views either side of the current one stay mounted. A page render is
 * 1696×2528, so every mounted image costs ~17 MB of decoded bitmap — a whole
 * book at once would run to hundreds of megabytes. One neighbour each way keeps
 * page turns instant without holding the book in memory.
 */
const WINDOW = 1;

/** Distance past the mounted window to warm in the HTTP cache. */
const PREFETCH = 2;

const SWIPE_THRESHOLD_PX = 48;

function readerPageUrl(project: string, page: ReaderPage) {
  return page.imageUrl ?? (page.hybrid
    ? pageCompositePreviewUrl(project, page.pageNumber, page.revision, "reader", page.letteringRevision)
    : pageRenderPreviewUrl(project, page.pageNumber, page.revision, "reader"));
}

interface BookReaderProps {
  project?: string;
  pages: ReaderPage[];
  title?: string;
  headerActions?: ReactNode;
  endContent?: ReactNode;
  closeLabel?: string;
  /** Named in every page's label when the book offers more than one language. */
  languageLabel?: string;
  /** Page to open on, when entering from a specific page rather than the cover. */
  initialPageNumber?: number;
  onClose: () => void;
}

function ReaderImage({
  project,
  page,
  fit,
  widthClass,
  alt,
}: {
  project: string;
  page: ReaderPage;
  fit: Fit;
  widthClass: string;
  alt: string;
}) {
  const { t } = useI18n();
  const [loaded, setLoaded] = useState(false);

  return (
    <div
      className={cn(
        "relative",
        widthClass,
        fit === "height" ? "flex h-full items-center justify-center" : "",
      )}
    >
      {!loaded && (
        <>
          <Skeleton className="absolute inset-0 h-full w-full" />
          <span className="sr-only">{t("Loading page…")}</span>
        </>
      )}
      <img
        src={readerPageUrl(project, page)}
        alt={alt}
        decoding="async"
        onLoad={() => setLoaded(true)}
        onError={() => setLoaded(true)}
        className={cn(
          "relative block bg-bristol transition-opacity duration-150",
          fit === "height"
            ? "max-h-full max-w-full w-auto object-contain"
            : "h-auto w-full",
          loaded ? "opacity-100" : "opacity-0",
        )}
      />
    </div>
  );
}

function ViewLayer({
  project,
  view,
  fit,
  isCurrent,
  label,
  languageLabel,
}: {
  project: string;
  view: ReaderView;
  fit: Fit;
  isCurrent: boolean;
  label: string;
  languageLabel?: string;
}) {
  const { t } = useI18n();
  const widthClass = view.kind === "facing"
    ? (fit === "height" ? "h-full" : "w-1/2")
    : (fit === "height" ? "h-full" : "w-full");

  return (
    <div
      // Neighbours stay mounted but out of the accessibility tree and tab
      // order, so a page turn is a decoded bitmap away rather than a fetch.
      inert={!isCurrent}
      aria-hidden={!isCurrent}
      className={cn(
        "absolute inset-0 p-3 transition-opacity duration-150 md:p-6",
        fit === "height"
          ? "flex items-center justify-center overflow-hidden"
          : "overflow-y-auto",
        isCurrent ? "opacity-100" : "pointer-events-none opacity-0",
      )}
    >
      <div
        className={cn(
          "mx-auto flex",
          fit === "height"
            ? "h-full max-w-full items-center justify-center"
            // Two pages side by side need twice the width of one, or a spread
            // reads at half the scale of the pages around it.
            : cn("w-full", view.kind === "single" ? "max-w-3xl" : "max-w-[96rem]"),
        )}
      >
        {view.pages.map((page) => (
          <ReaderImage
            // A new language is a new image: show its skeleton, not the old copy.
            key={`${page.pageNumber}-${page.imageUrl ?? ""}`}
            project={project}
            page={page}
            fit={fit}
            widthClass={widthClass}
            alt={`${label} — ${t("Page")} ${page.pageNumber}${languageLabel ? ` · ${languageLabel}` : ""}`}
          />
        ))}
      </div>
    </div>
  );
}

export function BookReader({ project = "", pages, initialPageNumber, onClose, title, headerActions, endContent, closeLabel, languageLabel }: BookReaderProps) {
  const { t } = useI18n();
  const [layout, setLayout] = useState<ReaderLayout>("spreads");
  const [fit, setFit] = useState<Fit>("height");
  const dialogRef = useRef<HTMLDivElement>(null);
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const touchStart = useRef<{ x: number; y: number } | null>(null);
  useDialogFocus(dialogRef, { onClose, initialFocusRef: closeButtonRef });
  const inspector = useImageViewer();

  const views = useMemo(() => buildReaderViews(pages, layout), [pages, layout]);
  const [index, setIndex] = useState(() =>
    initialPageNumber
      ? viewIndexForPage(buildReaderViews(pages, "spreads"), initialPageNumber)
      : 0,
  );
  const lastIndex = Math.max(views.length - 1 + (endContent ? 1 : 0), 0);
  const safeIndex = Math.min(index, lastIndex);
  const showingEnd = !!endContent && safeIndex === views.length;
  const current = views[safeIndex];

  function goTo(next: number) {
    setIndex(Math.max(0, Math.min(next, lastIndex)));
  }

  /** Switching layout must land on the page the reader was already showing. */
  function changeLayout(next: ReaderLayout) {
    if (showingEnd) {
      setLayout(next);
      setIndex(buildReaderViews(pages, next).length);
      return;
    }
    const anchor = current?.pages[0].pageNumber;
    setLayout(next);
    if (anchor !== undefined) {
      setIndex(viewIndexForPage(buildReaderViews(pages, next), anchor));
    }
  }

  // Warm the HTTP cache just past the mounted window so a fast reader never
  // outruns the fetch. Detached Images are collected; the cache entry is not.
  useEffect(() => {
    for (let offset = WINDOW + 1; offset <= PREFETCH; offset += 1) {
      for (const step of [safeIndex + offset, safeIndex - offset]) {
        views[step]?.pages.forEach((page) => {
          const image = new Image();
          image.src = readerPageUrl(project, page);
        });
      }
    }
  }, [project, views, safeIndex]);

  const onKey = useEffectEvent((event: KeyboardEvent) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target instanceof HTMLElement && (
      target.matches("input, textarea, select") || target.isContentEditable ||
      (event.key === " " && target.closest("button, a"))
    )) return;
    switch (event.key) {
      case "Escape":
        return;
      case "ArrowRight":
      case "PageDown":
      case " ":
        event.preventDefault();
        goTo(safeIndex + 1);
        return;
      case "ArrowLeft":
      case "PageUp":
        event.preventDefault();
        goTo(safeIndex - 1);
        return;
      case "Home":
        event.preventDefault();
        goTo(0);
        return;
      case "End":
        event.preventDefault();
        goTo(lastIndex);
        return;
      default:
        return;
    }
  });

  useEffect(() => {

    function handler(event: KeyboardEvent) {
      onKey(event);
    }

    window.addEventListener("keydown", handler);
    return () => {
      window.removeEventListener("keydown", handler);
    };
  }, []);

  const label = showingEnd ? t("End of book") : viewLabel(current, t("Page"), t("Pages"));
  const atStart = safeIndex <= 0;
  const atEnd = safeIndex >= lastIndex;

  return (
    <div
      ref={dialogRef}
      role="dialog"
      aria-modal="true"
      aria-label={t("Book reader")}
      tabIndex={-1}
      className="fixed inset-0 z-[130] flex flex-col bg-ink-black"
      onTouchStart={(event) => {
        if (event.touches.length !== 1 || (event.target instanceof HTMLElement && event.target.closest("button, input, select, a, summary"))) {
          touchStart.current = null;
          return;
        }
        touchStart.current = { x: event.touches[0].clientX, y: event.touches[0].clientY };
      }}
      onTouchEnd={(event) => {
        const start = touchStart.current;
        touchStart.current = null;
        const end = event.changedTouches[0];
        if (!start || !end) return;
        const delta = end.clientX - start.x;
        if (Math.abs(delta) < SWIPE_THRESHOLD_PX || Math.abs(delta) <= Math.abs(end.clientY - start.y)) return;
        goTo(safeIndex + (delta < 0 ? 1 : -1));
      }}
    >
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b-[2px] border-bristol/25 px-3 py-2 md:px-5 md:py-3">
        <p className="font-display text-lg font-black uppercase text-bristol">
          {title ?? t("READING")}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          {headerActions}
          {current && !showingEnd && (
            <button
              type="button"
              onClick={() => inspector.open(
                pages.map((page) => ({ src: readerPageUrl(project, page), alt: `${t("Page")} ${page.pageNumber}` })),
                pages.indexOf(current.pages[0]),
              )}
              className="flex min-h-11 items-center gap-2 border-[2px] border-bristol/40 px-3 font-meta text-xs font-bold text-bristol transition-colors hover:border-bristol"
            >
              <Icon name="zoom-in" size={14} />{t("ZOOM")}
            </button>
          )}
          <button
            type="button"
            onClick={() => changeLayout(layout === "spreads" ? "single" : "spreads")}
            aria-pressed={layout === "spreads"}
            className="min-h-11 border-[2px] border-bristol/40 px-3 font-meta text-xs font-bold text-bristol transition-colors hover:border-bristol"
          >
            {layout === "spreads" ? t("SPREADS") : t("SINGLE PAGE")}
          </button>
          <button
            type="button"
            onClick={() => setFit(fit === "height" ? "width" : "height")}
            aria-pressed={fit === "width"}
            className="min-h-11 border-[2px] border-bristol/40 px-3 font-meta text-xs font-bold text-bristol transition-colors hover:border-bristol"
          >
            {fit === "height" ? t("FIT HEIGHT") : t("FIT WIDTH")}
          </button>
          <button
            ref={closeButtonRef}
            type="button"
            onClick={onClose}
            aria-label={t("Close reader")}
            className="flex h-11 w-11 items-center justify-center border-[2px] border-bristol/40 text-bristol transition-colors hover:border-bristol"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      </header>

      <div className="relative min-h-0 flex-1">
        {views.slice(Math.max(0, safeIndex - WINDOW), safeIndex + WINDOW + 1).map((view) => (
          <ViewLayer
            key={view.key}
            project={project}
            view={view}
            fit={fit}
            isCurrent={view.key === current?.key}
            label={label}
            languageLabel={languageLabel}
          />
        ))}

        {showingEnd && <div className="absolute inset-0 overflow-y-auto bg-pulp-paper p-4 text-ink-black md:p-8">{endContent}</div>}

        {/* Click-to-turn only in fit-height: fit-width is a scrolling read. */}
        {fit === "height" && !showingEnd && (
          <>
            <button
              type="button"
              onClick={() => goTo(safeIndex - 1)}
              disabled={atStart}
              aria-label={t("Previous page")}
              className="group absolute inset-y-0 left-0 flex w-[18%] items-center justify-start pl-2 disabled:pointer-events-none md:pl-4"
            >
              <span className="flex h-11 w-11 items-center justify-center border-[2px] border-bristol/0 bg-ink-black/0 text-bristol/0 transition-colors group-hover:border-bristol/50 group-hover:bg-ink-black/70 group-hover:text-bristol group-focus-visible:border-bristol group-focus-visible:bg-ink-black/70 group-focus-visible:text-bristol">
                <Icon name="chevron-left" size={18} />
              </span>
            </button>
            <button
              type="button"
              onClick={() => goTo(safeIndex + 1)}
              disabled={atEnd}
              aria-label={t("Next page")}
              className="group absolute inset-y-0 right-0 flex w-[18%] items-center justify-end pr-2 disabled:pointer-events-none md:pr-4"
            >
              <span className="flex h-11 w-11 items-center justify-center border-[2px] border-bristol/0 bg-ink-black/0 text-bristol/0 transition-colors group-hover:border-bristol/50 group-hover:bg-ink-black/70 group-hover:text-bristol group-focus-visible:border-bristol group-focus-visible:bg-ink-black/70 group-focus-visible:text-bristol">
                <Icon name="chevron-right" size={18} />
              </span>
            </button>
          </>
        )}
      </div>

      <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t-[2px] border-bristol/25 px-3 py-2 md:px-5 md:py-3">
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => goTo(safeIndex - 1)}
            disabled={atStart}
            aria-label={t("Previous page")}
            className="flex h-11 w-11 items-center justify-center border-[2px] border-bristol/40 text-bristol transition-colors hover:border-bristol disabled:opacity-35"
          >
            <Icon name="chevron-left" size={14} />
          </button>
          {atEnd ? (
            <button type="button" onClick={onClose} className="min-h-11 border-[2px] border-bristol/40 px-3 font-meta text-xs font-bold text-bristol hover:border-bristol">
              {closeLabel ?? t("Back to edition")}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => goTo(safeIndex + 1)}
              aria-label={t("Next page")}
              className="flex h-11 w-11 items-center justify-center border-[2px] border-bristol/40 text-bristol transition-colors hover:border-bristol"
            >
              <Icon name="chevron-right" size={14} />
            </button>
          )}
        </div>

        <p aria-live="polite" className="font-meta text-xs font-bold tracking-[0.12em] text-bristol">
          {label}
          {atEnd && !showingEnd && <span className="ml-2">{t("End of book")}</span>}
          <span className="text-bristol/55">
            {" · "}
            {pages.length} {pages.length === 1 ? t("page") : t("pages")}
          </span>
        </p>

        <input
          type="range"
          min={0}
          max={lastIndex}
          value={safeIndex}
          onChange={(event) => goTo(Number(event.target.value))}
          aria-label={t("Jump to page")}
          aria-valuetext={t("{label} of {total}", { label: label, total: String(pages.length) })}
          className="h-11 w-full max-w-xs accent-hero-red md:w-64"
        />
      </footer>
      {inspector.viewer}
    </div>
  );
}

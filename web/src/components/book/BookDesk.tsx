import { useEffect, useMemo, type ReactNode } from "react";
import { ChevronLeft, ChevronRight, Maximize2 } from "lucide-react";
import { useI18n } from "../../i18n";
import { type DeskView, type ReaderPage } from "../../lib/bookReader";
import { pageDisplayImage } from "../../lib/pageState";
import { cn } from "../../lib/cn";
import { ScrollStripControls } from "../ui/ScrollStrip";
import { useScrollStrip } from "../ui/useScrollStrip";

/**
 * The finished book open on the table: one spread at a time, as large as the
 * desk allows, with a strip of every spread underneath.
 */
export function BookDesk({ project, views, index, onIndex, coverSrc, flagged, onRead, toolbar }: {
  project: string;
  views: DeskView[];
  index: number;
  onIndex: (index: number) => void;
  coverSrc: string;
  /** Pages with something that blocks export. */
  flagged: Set<number>;
  onRead: () => void;
  toolbar?: ReactNode;
}) {
  const { t } = useI18n();
  const view = views[Math.min(index, views.length - 1)];
  const last = views.length - 1;
  const { attach: stripRef, element: stripElement, ...strip } = useScrollStrip<HTMLOListElement>();

  useEffect(() => {
    function turn(event: KeyboardEvent) {
      const target = event.target instanceof Element ? event.target : null;
      if (event.defaultPrevented || event.metaKey || event.ctrlKey || event.altKey) return;
      if (target?.closest("input, textarea, select, [contenteditable='true'], [role='dialog'], [role='alertdialog'], [role='slider']")) return;
      if (document.querySelector("[role='dialog'][aria-modal='true']")) return;
      if (event.key === "ArrowRight" && index < last) onIndex(index + 1);
      else if (event.key === "ArrowLeft" && index > 0) onIndex(index - 1);
    }
    window.addEventListener("keydown", turn);
    return () => window.removeEventListener("keydown", turn);
  }, [index, last, onIndex]);

  useEffect(() => {
    stripElement?.querySelector<HTMLElement>("[aria-current='true']")?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [index, stripElement]);

  const label = (item: DeskView) => item.cover ? t("Cover")
    : item.pages.length === 1 ? `${t("Page")} ${item.pages[0].pageNumber}`
    : `${t("Pages")} ${item.pages[0].pageNumber}–${item.pages[item.pages.length - 1].pageNumber}`;

  return (
    <section aria-label={t("Your book")} className="benday-ink flex min-h-[32rem] min-w-0 flex-1 flex-col text-pulp-paper studio-desktop:min-h-0">
      <div className="flex min-h-12 flex-wrap items-center gap-x-4 gap-y-2 px-5 pt-3 sm:px-6">
        <p aria-live="polite" className="font-meta text-xs font-medium text-on-chrome-muted">
          {view ? label(view) : null}
          {views.length > 0 && <span className="ml-2 tabular-nums text-pulp-paper/45">{index + 1} / {views.length}</span>}
        </p>
        <div className="ml-auto flex items-center gap-2">
          {toolbar}
          <button type="button" onClick={onRead}
            className="inline-flex h-8 items-center gap-2 border border-pulp-paper/25 px-3 font-meta text-xs font-semibold text-pulp-paper transition-colors hover:border-pulp-paper hover:bg-pulp-paper hover:text-ink-black focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-narrator-gold">
            <Maximize2 size={14} aria-hidden="true" />{t("Read your book")}
          </button>
        </div>
      </div>

      <div className="relative flex min-h-[16rem] flex-1 items-center justify-center px-14 py-5 [--stage-h:60svh] [container-type:inline-size] sm:px-16 studio-desktop:min-h-0 studio-desktop:[--stage-h:100cqh] studio-desktop:[container-type:size]">
        {view && <Spread project={project} view={view} coverSrc={coverSrc} onRead={onRead} />}
        <TurnButton side="left" disabled={index <= 0} label={t("Previous spread")} onClick={() => onIndex(index - 1)} />
        <TurnButton side="right" disabled={index >= last} label={t("Next spread")} onClick={() => onIndex(index + 1)} />
      </div>

      <nav aria-label={t("Spreads")} className="relative border-t border-pulp-paper/10 bg-ink-black/40">
        <ScrollStripControls strip={strip} />
        <ol ref={stripRef} className="flex gap-2 overflow-x-auto px-5 py-3 [scrollbar-width:none] sm:px-6">
          {views.map((item, position) => {
            const current = position === index;
            const needsYou = !item.cover && item.pages.some((page) => flagged.has(page.pageNumber));
            return (
              <li key={item.key} className="shrink-0">
                <button type="button" aria-current={current ? "true" : undefined} onClick={() => onIndex(position)}
                  aria-label={needsYou ? `${label(item)} · ${t("Blocks export")}` : label(item)}
                  className={cn("relative flex h-14 items-stretch gap-px p-0.5 outline outline-1 transition-[outline-color,opacity]",
                    current ? "outline-narrator-gold opacity-100" : "outline-pulp-paper/10 opacity-60 hover:opacity-100 hover:outline-pulp-paper/40",
                    "focus-visible:outline-2 focus-visible:outline-narrator-gold")}>
                  {item.cover
                    ? <img src={coverSrc} alt="" loading="lazy" decoding="async" className="aspect-[2/3] h-full bg-ink-black object-cover" />
                    : item.pages.map((page) => (
                      <img key={page.pageNumber} src={pageDisplayImage(project, page, "thumbnail")} alt="" loading="lazy" decoding="async"
                        className={cn("h-full bg-ink-black object-cover", item.kind === "wide" ? "aspect-[4/3]" : "aspect-[2/3]")} />
                    ))}
                  {needsYou && <span aria-hidden="true" className="absolute -right-1 -top-1 size-2.5 border border-ink-black bg-hero-red" />}
                </button>
              </li>
            );
          })}
        </ol>
      </nav>
    </section>
  );
}

/** One turn of the book, fitted to the desk. A lone page sits on the side it is printed on. */
function Spread({ project, view, coverSrc, onRead }: { project: string; view: DeskView; coverSrc: string; onRead: () => void }) {
  const { t } = useI18n();
  const shadow = "shadow-[0_30px_60px_-20px_rgb(0_0_0/0.8),0_0_0_1px_rgb(252_250_237/0.1)]";
  // Two 2:3 pages side by side: the open book is 4:3. The desk sets --stage-h.
  const frame = { width: "min(100cqw, calc(var(--stage-h) * 4 / 3))", aspectRatio: "4 / 3" };
  const pages = useMemo(() => (view.cover ? [] : view.pages), [view]);

  if (view.cover) {
    return (
      <div className="flex justify-end" style={frame}>
        <button type="button" onClick={onRead} aria-label={t("Open the book reader")}
          className={cn("h-full w-1/2 bg-ink-black shadow-[6px_6px_0_0_var(--color-narrator-gold)] transition-transform hover:-translate-y-px focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-narrator-gold")}>
          <img src={coverSrc} alt={t("Book cover")} decoding="async" className="h-full w-full object-cover" />
        </button>
      </div>
    );
  }

  const image = (page: ReaderPage, className: string) => (
    <img key={page.pageNumber} src={pageDisplayImage(project, page)} alt={`${t("Page")} ${page.pageNumber}`} decoding="async"
      className={cn("h-full bg-ink-black object-contain", className)} />
  );

  if (view.kind === "wide") {
    return <div className={cn("bg-ink-black", shadow)} style={frame}>{image(pages[0], "w-full")}</div>;
  }
  if (view.kind === "facing") {
    return (
      <div className={cn("relative flex bg-ink-black", shadow)} style={frame}>
        {image(pages[0], "w-1/2")}
        {image(pages[1], "w-1/2")}
        {/* The fold: pages curve into the gutter. */}
        <span aria-hidden="true" className="pointer-events-none absolute inset-y-0 left-1/2 w-16 -translate-x-1/2 bg-[linear-gradient(90deg,transparent,rgb(0_0_0/0.28)_45%,rgb(0_0_0/0.4)_50%,rgb(0_0_0/0.28)_55%,transparent)]" />
      </div>
    );
  }
  const side = pages[0].spreadRole === "left" ? "justify-start" : pages[0].spreadRole === "right" ? "justify-end" : "justify-center";
  return (
    <div className={cn("flex", side)} style={frame}>
      <div className={cn("h-full w-1/2 bg-ink-black", shadow)}>{image(pages[0], "w-full")}</div>
    </div>
  );
}

function TurnButton({ side, disabled, label, onClick }: { side: "left" | "right"; disabled: boolean; label: string; onClick: () => void }) {
  const Icon = side === "left" ? ChevronLeft : ChevronRight;
  return (
    <button type="button" aria-label={label} disabled={disabled} onClick={onClick}
      className={cn("absolute top-1/2 flex size-10 -translate-y-1/2 items-center justify-center border border-pulp-paper/20 bg-ink-black/60 text-pulp-paper transition-colors",
        "hover:border-pulp-paper hover:bg-pulp-paper hover:text-ink-black disabled:pointer-events-none disabled:opacity-25",
        "focus-visible:outline focus-visible:outline-2 focus-visible:outline-narrator-gold",
        side === "left" ? "left-3 sm:left-4" : "right-3 sm:right-4")}>
      <Icon size={20} aria-hidden="true" />
    </button>
  );
}

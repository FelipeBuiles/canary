import { useEffect, useRef, useState } from "react";
import type { ComicPage, PageSummary } from "../../types/api";
import { Button } from "../ui/Button";
import { pagePreviewUrl } from "../../api/pages";
import { cn } from "../../lib/cn";

interface PreviewModeProps {
  project: string;
  pages: (ComicPage | undefined)[];
  pageList: PageSummary[];
  isLoading: boolean;
  pageIdx: number;
  isExporting: boolean;
  onPageSelect: (idx: number) => void;
  onExport: (format: "pdf" | "cbz") => void;
}

export function PreviewMode({
  project,
  pages,
  pageList,
  isLoading,
  pageIdx,
  isExporting,
  onPageSelect,
  onExport,
}: PreviewModeProps) {
  // Snap to even index so spreads are always left/right pairs
  const spreadStart = pageIdx % 2 === 0 ? pageIdx : pageIdx - 1;
  const totalSpreads = Math.ceil(pageList.length / 2);
  const spreadIdx = Math.floor(spreadStart / 2);

  const leftSummary = pageList[spreadStart];
  const rightSummary = pageList[spreadStart + 1];

  const totalBubbles = pages.flatMap((p) => p?.panels.flatMap((panel) => panel.bubbles) ?? []).length;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-preview-tint">
      {/* Preview header */}
      <div className="flex shrink-0 items-center justify-between border-b-[2px] border-ink-black bg-pulp-paper px-6 py-3">
        <div className="flex items-center gap-5">
          <div className="font-display text-[1.4rem] font-black uppercase leading-none tracking-[-0.04em] [font-stretch:75%]">
            SPREAD {spreadIdx + 1} / {totalSpreads}
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={() => onPageSelect(Math.max(0, spreadStart - 2))}
              disabled={spreadStart === 0}
              className="border-[2px] border-ink-black px-2.5 py-1 font-meta text-[0.6rem] tracking-[0.1em] transition-colors hover:bg-surface-container disabled:opacity-40"
            >
              ← PREV
            </button>
            <button
              onClick={() => onPageSelect(Math.min(pageList.length - 1, spreadStart + 2))}
              disabled={spreadStart + 2 >= pageList.length}
              className="border-[2px] border-ink-black px-2.5 py-1 font-meta text-[0.6rem] tracking-[0.1em] transition-colors hover:bg-surface-container disabled:opacity-40"
            >
              NEXT →
            </button>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Button size="sm" onClick={() => onExport("pdf")} disabled={isExporting}>
            {isExporting ? "EXPORTING..." : "Export PDF"}
            <kbd className="ml-0.5 rounded bg-hero-red/20 px-1 py-0.5 text-[0.48rem]">⌘E</kbd>
          </Button>
          <Button size="sm" variant="secondary" onClick={() => onExport("cbz")} disabled={isExporting}>
            CBZ
          </Button>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Spread view */}
        <div className="flex min-w-0 flex-1 items-center justify-center overflow-auto p-8">
          {isLoading ? (
            <div className="flex h-40 items-center justify-center">
              <p className="font-meta text-[0.6rem] tracking-[0.2em] text-ink-black/40">
                LOADING PREVIEW...
              </p>
            </div>
          ) : (
            <div className="flex shadow-ink-lg">
              {leftSummary && (
                <PreviewPageSheet project={project} summary={leftSummary} isLeft />
              )}
              {rightSummary && (
                <PreviewPageSheet project={project} summary={rightSummary} isLeft={false} />
              )}
            </div>
          )}
        </div>

        {/* Right: export info + page strip */}
        <aside className="w-[220px] shrink-0 overflow-y-auto border-l-[2px] border-ink-black bg-pulp-paper p-3 space-y-4">
          {/* Export info */}
          <div className="border-[2px] border-ink-black bg-surface-container p-3 shadow-ink-sm">
            <div className="mb-2 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">
              EXPORT INFO
            </div>
            <div className="space-y-1.5">
              {[
                { label: "FORMAT", value: "PDF / CBZ" },
                { label: "PAGES", value: String(pageList.length) },
                { label: "BUBBLES", value: String(totalBubbles) },
              ].map(({ label, value }) => (
                <div key={label} className="flex items-center justify-between">
                  <span className="font-meta text-[0.55rem] tracking-[0.12em] text-ink-black/50">
                    {label}
                  </span>
                  <span className="font-meta text-[0.65rem] font-bold tracking-[0.1em]">
                    {value}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Page thumbnails */}
          <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">
            ALL PAGES
          </div>
          <div className="space-y-1.5">
            {pageList.map((summary, idx) => {
              const inSpread = idx === spreadStart || idx === spreadStart + 1;
              return (
                <button
                  key={summary.page_number}
                  onClick={() => onPageSelect(idx % 2 === 0 ? idx : idx - 1)}
                  className={cn(
                    "w-full border-[2px] px-2.5 py-1.5 text-left font-meta text-[0.58rem] tracking-[0.1em] transition-colors",
                    inSpread
                      ? "border-hero-red bg-chip-red text-hero-red"
                      : "border-ink-black bg-pulp-paper hover:bg-surface-container",
                  )}
                >
                  PAGE {String(summary.page_number).padStart(2, "0")} ·{" "}
                  {summary.panel_count}p
                </button>
              );
            })}
          </div>
        </aside>
      </div>
    </div>
  );
}

function PreviewPageSheet({
  project,
  summary,
  isLeft,
}: {
  project: string;
  summary: PageSummary;
  isLeft: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [scale, setScale] = useState(0.145);
  const src = pagePreviewUrl(project, summary.page_number);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => {
      const w = el.clientWidth;
      const h = el.clientHeight;
      if (w > 0 && h > 0) {
        setScale(Math.min(w / 2480, h / 3508));
      }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return (
    <div
      className={cn(
        "flex flex-col bg-pulp-paper",
        isLeft
          ? "border-y-[2px] border-l-[2px] border-r border-ink-black border-r-ink-black/20"
          : "border-y-[2px] border-r-[2px] border-l border-ink-black border-l-ink-black/20",
      )}
      style={{ width: 360, minHeight: 509 }}
    >
      <div ref={containerRef} className="flex-1 overflow-hidden bg-ink-black/5">
        <iframe
          src={src}
          title={`Page ${summary.page_number} preview`}
          className="pointer-events-none border-0 bg-white"
          style={{ width: 2480, height: 3508, transform: `scale(${scale})`, transformOrigin: "top left" }}
          loading="lazy"
        />
      </div>
      <div className="flex items-center justify-between border-t border-ink-black/15 px-3 py-1.5">
        <span className="font-meta text-[0.5rem] tracking-[0.1em] text-ink-black/40">
          PAGE {String(summary.page_number).padStart(2, "0")}
        </span>
        <span className="font-meta text-[0.5rem] tracking-[0.1em] text-ink-black/35">
          {summary.panel_count}p
        </span>
      </div>
    </div>
  );
}

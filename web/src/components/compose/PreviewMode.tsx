import { useEffect, useRef, useState } from "react";
import type { ComicPage, PageSummary } from "../../types/api";
import { Button } from "../ui/Button";
import { pagePreviewUrl } from "../../api/pages";
import { cn } from "../../lib/cn";

const THEMES = [
  { id: "default", label: "Default" },
  { id: "noir", label: "Noir" },
  { id: "manga", label: "Manga" },
  { id: "vintage", label: "Vintage" },
  { id: "painted", label: "Painted" },
] as const;

const LANGUAGES = [
  { value: "en" as const, label: "English" },
  { value: "es" as const, label: "Español" },
  { value: "fr" as const, label: "Français" },
];

interface PreviewModeProps {
  project: string;
  pages: (ComicPage | undefined)[];
  pageList: PageSummary[];
  isLoading: boolean;
  pageIdx: number;
  isExporting: boolean;
  activeTheme: string;
  outputLanguage: "en" | "es" | "fr";
  isTranslatingBubbles: boolean;
  onPageSelect: (idx: number) => void;
  onExport: (format: "pdf" | "cbz") => void;
  onThemeChange: (theme: string) => void;
  onOutputLanguageChange: (lang: "en" | "es" | "fr") => void;
  onTranslateBubbles: (lang: "en" | "es" | "fr") => void;
}

export function PreviewMode({
  project,
  pages,
  pageList,
  isLoading,
  pageIdx,
  isExporting,
  activeTheme,
  outputLanguage,
  isTranslatingBubbles,
  onPageSelect,
  onExport,
  onThemeChange,
  onOutputLanguageChange,
  onTranslateBubbles,
}: PreviewModeProps) {
  const spreadStart = pageIdx % 2 === 0 ? pageIdx : pageIdx - 1;
  const totalSpreads = Math.ceil(pageList.length / 2);
  const spreadIdx = Math.floor(spreadStart / 2);

  const leftSummary = pageList[spreadStart];
  const rightSummary = pageList[spreadStart + 1];

  const totalBubbles = pages.flatMap((p) => p?.panels.flatMap((panel) => panel.bubbles) ?? []).length;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-preview-tint">
      {/* Spread nav header */}
      <div className="flex shrink-0 items-center justify-between border-b-[2px] border-ink-black bg-pulp-paper px-6 py-3">
        <div className="flex items-center gap-4">
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
      </div>

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {/* Spread view */}
        <SpreadView
          project={project}
          isLoading={isLoading}
          leftSummary={leftSummary}
          rightSummary={rightSummary}
        />

        {/* Right sidebar */}
        <aside className="w-[220px] shrink-0 overflow-y-auto border-l-[2px] border-ink-black bg-pulp-paper p-3 space-y-4">

          {/* Theme */}
          <div className="border-[2px] border-ink-black bg-surface-container p-3 shadow-ink-sm">
            <div className="mb-2 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">THEME</div>
            <div className="flex flex-wrap gap-2">
              {THEMES.map((t) => (
                <button
                  key={t.id}
                  onClick={() => onThemeChange(t.id)}
                  className={cn(
                    "border-[2px] px-2.5 py-1 font-meta text-[0.52rem] tracking-[0.08em] transition-colors",
                    t.id === activeTheme
                      ? "border-ink-black bg-ink-black text-pulp-paper"
                      : "border-ink-black/25 bg-pulp-paper text-ink-black hover:bg-surface-container",
                  )}
                >
                  {t.label.toUpperCase()}
                </button>
              ))}
            </div>
          </div>

          {/* Translate */}
          <div className="border-[2px] border-ink-black bg-surface-container p-3 shadow-ink-sm">
            <div className="mb-2 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">TRANSLATE</div>
            <div className="mb-2 flex flex-wrap gap-1.5">
              {LANGUAGES.map((lang) => (
                <button
                  key={lang.value}
                  onClick={() => onOutputLanguageChange(lang.value)}
                  disabled={isTranslatingBubbles}
                  className={cn(
                    "border-[2px] border-ink-black px-2 py-1 font-meta text-[0.52rem] tracking-[0.08em] transition-colors disabled:opacity-50",
                    outputLanguage === lang.value
                      ? "bg-ink-black text-pulp-paper"
                      : "bg-pulp-paper hover:bg-surface-container",
                  )}
                >
                  {lang.label}
                </button>
              ))}
            </div>
            <Button
              size="sm"
              variant="secondary"
              fullWidth
              onClick={() => onTranslateBubbles(outputLanguage)}
              disabled={isTranslatingBubbles}
            >
              {isTranslatingBubbles ? "TRANSLATING..." : "TRANSLATE ALL"}
            </Button>
          </div>

          {/* Export info */}
          <div className="border-[2px] border-ink-black bg-surface-container p-3 shadow-ink-sm">
            <div className="mb-2 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">EXPORT</div>
            <div className="mb-3 space-y-1.5">
              {[
                { label: "PAGES", value: String(pageList.length) },
                { label: "BUBBLES", value: String(totalBubbles) },
              ].map(({ label, value }) => (
                <div key={label} className="flex items-center justify-between">
                  <span className="font-meta text-[0.55rem] tracking-[0.12em] text-ink-black/50">{label}</span>
                  <span className="font-meta text-[0.65rem] font-bold tracking-[0.1em]">{value}</span>
                </div>
              ))}
            </div>
            <div className="space-y-1.5">
              <Button size="sm" fullWidth onClick={() => onExport("pdf")} disabled={isExporting}>
                {isExporting ? "EXPORTING..." : "EXPORT PDF"}
              </Button>
              <Button size="sm" variant="secondary" fullWidth onClick={() => onExport("cbz")} disabled={isExporting}>
                CBZ
              </Button>
            </div>
          </div>

          {/* Page list */}
          <div>
            <div className="mb-2 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">ALL PAGES</div>
            <div className="space-y-1">
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
                    PAGE {String(summary.page_number).padStart(2, "0")} · {summary.panel_count}p
                  </button>
                );
              })}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

const PAGE_W = 2480;
const PAGE_H = 3508;

function SpreadView({
  project,
  isLoading,
  leftSummary,
  rightSummary,
}: {
  project: string;
  isLoading: boolean;
  leftSummary: PageSummary | undefined;
  rightSummary: PageSummary | undefined;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [fitScale, setFitScale] = useState(0.2);
  const [zoom, setZoom] = useState(1);
  const panRef = useRef<{ startX: number; startY: number; left: number; top: number } | null>(null);

  const pageCount = leftSummary && rightSummary ? 2 : 1;
  const nativeW = PAGE_W * pageCount;
  const nativeH = PAGE_H;

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const compute = () => {
      const w = el.clientWidth - 64;
      const h = el.clientHeight - 64;
      if (w <= 0 || h <= 0) return;
      const s = Math.min(h / nativeH, w / nativeW);
      setFitScale(isFinite(s) && s > 0 ? s : 0.2);
    };
    compute();
    const ro = new ResizeObserver(compute);
    ro.observe(el);
    return () => ro.disconnect();
  }, [nativeW, nativeH]);

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      if (!e.ctrlKey && !e.metaKey) return;
      e.preventDefault();
      const factor = e.deltaY < 0 ? 1.1 : 0.9;
      setZoom((z) => parseFloat(Math.max(0.5, Math.min(3, z * factor)).toFixed(3)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, []);

  const scale = fitScale * zoom;
  const scaledW = Math.round(nativeW * scale);
  const scaledH = Math.round(nativeH * scale);

  function handleMouseDown(e: React.MouseEvent<HTMLDivElement>) {
    if (zoom <= 1 || e.button !== 0) return;
    const el = containerRef.current;
    if (!el) return;
    panRef.current = { startX: e.clientX, startY: e.clientY, left: el.scrollLeft, top: el.scrollTop };
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
    if (containerRef.current) containerRef.current.style.cursor = zoom > 1 ? "grab" : "default";
  }

  return (
    <div
      ref={containerRef}
      className="flex min-w-0 flex-1 overflow-auto p-8"
      style={{ cursor: zoom > 1 ? "grab" : "default" }}
      onMouseDown={handleMouseDown}
      onMouseMove={handleMouseMove}
      onMouseUp={stopPan}
      onMouseLeave={stopPan}
    >
      {isLoading ? (
        <div className="flex h-40 w-full items-center justify-center">
          <p className="font-meta text-[0.6rem] tracking-[0.2em] text-ink-black/40">LOADING PREVIEW...</p>
        </div>
      ) : (
        <div style={{ width: scaledW, height: scaledH, margin: "auto", position: "relative", flexShrink: 0 }}>
          <div
            className="flex shadow-ink-lg"
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
            {leftSummary && <PreviewPageSheet project={project} summary={leftSummary} isLeft />}
            {rightSummary && <PreviewPageSheet project={project} summary={rightSummary} isLeft={false} />}
          </div>
        </div>
      )}
    </div>
  );
}

function PreviewPageSheet({ project, summary, isLeft }: { project: string; summary: PageSummary; isLeft: boolean }) {
  const src = pagePreviewUrl(project, summary.page_number);
  return (
    <div
      className={cn(
        "bg-pulp-paper",
        isLeft
          ? "border-y-[2px] border-l-[2px] border-r border-ink-black border-r-ink-black/20"
          : "border-y-[2px] border-r-[2px] border-l border-ink-black border-l-ink-black/20",
      )}
      style={{ width: PAGE_W, height: PAGE_H, flexShrink: 0 }}
    >
      <iframe
        src={src}
        title={`Page ${summary.page_number} preview`}
        className="pointer-events-none border-0 bg-white"
        style={{ width: PAGE_W, height: PAGE_H, display: "block" }}
        loading="lazy"
      />
    </div>
  );
}

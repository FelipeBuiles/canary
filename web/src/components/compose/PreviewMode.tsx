import { useState } from "react";
import type { ComicPage, PageSummary } from "../../types/api";
import { Button } from "../ui/Button";
import { ConfirmDrawer } from "../composites";
import { pagePreviewUrl } from "../../api/pages";
import { cn } from "../../lib/cn";
import type { ComposeIssue } from "../../lib/issueEngine";
import { ScaledContainer } from "./ScaledContainer";
import { PAGE_W, PAGE_H } from "./layouts";

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
  outputLanguage: "en" | "es" | "fr";
  isTranslatingBubbles: boolean;
  issues: ComposeIssue[];
  onPageSelect: (idx: number) => void;
  onExport: (format: "pdf" | "cbz") => void;
  onOutputLanguageChange: (lang: "en" | "es" | "fr") => void;
  onTranslateBubbles: (lang: "en" | "es" | "fr") => void;
}

function buildExportDrawerBody(issues: ComposeIssue[]): string {
  const errors = issues.filter((i) => i.severity === "error").length;
  const warnings = issues.filter((i) => i.severity === "warning").length;
  const parts: string[] = [];
  if (errors > 0) parts.push(`${errors} need${errors === 1 ? "s" : ""} you`);
  if (warnings > 0) parts.push(`${warnings} suggestion${warnings !== 1 ? "s" : ""}`);
  const summary = parts.join(" and ");
  return (
    `${summary} remain${issues.length === 1 ? "s" : ""} open. ` +
    `You can still export; fixing them first gives the best result.`
  );
}

export function PreviewMode({
  project,
  pages,
  pageList,
  isLoading,
  pageIdx,
  isExporting,
  outputLanguage,
  isTranslatingBubbles,
  issues,
  onPageSelect,
  onExport,
  onOutputLanguageChange,
  onTranslateBubbles,
}: PreviewModeProps) {
  const [exportDrawerFormat, setExportDrawerFormat] = useState<"pdf" | "cbz" | null>(null);
  const blockingIssues = issues.filter((i) => i.severity === "error");

  function handleExportClick(format: "pdf" | "cbz") {
    if (blockingIssues.length > 0 || issues.length > 0) {
      setExportDrawerFormat(format);
    } else {
      onExport(format);
    }
  }
  const spreadStart = pageIdx % 2 === 0 ? pageIdx : pageIdx - 1;
  const totalSpreads = Math.ceil(pageList.length / 2);
  const spreadIdx = Math.floor(spreadStart / 2);

  const leftSummary = pageList[spreadStart];
  const rightSummary = pageList[spreadStart + 1];

  const loadedPages = pages.filter((p): p is ComicPage => p !== undefined);
  const totalPanels = loadedPages.reduce((acc, p) => acc + p.panels.length, 0);
  const totalLettering = loadedPages.reduce(
    (acc, p) => acc + p.panels.reduce((a, panel) => a + panel.bubbles.length + (panel.sfx?.length ?? 0), 0),
    0,
  );

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

      <div className="flex min-h-0 flex-1 flex-col overflow-y-auto md:flex-row md:overflow-hidden">
        {/* Spread view */}
        <div className="flex min-h-[42vh] min-w-0 shrink-0 md:min-h-0 md:flex-1">
          <SpreadView
            project={project}
            isLoading={isLoading}
            leftSummary={leftSummary}
            rightSummary={rightSummary}
          />
        </div>

        {/* Export ConfirmDrawer */}
        <ConfirmDrawer
          open={exportDrawerFormat !== null}
          title="Export with open issues?"
          body={exportDrawerFormat !== null ? buildExportDrawerBody(issues) : ""}
          confirmLabel={`EXPORT ${exportDrawerFormat?.toUpperCase()} ANYWAY`}
          busy={isExporting}
          onConfirm={() => {
            if (exportDrawerFormat) onExport(exportDrawerFormat);
            setExportDrawerFormat(null);
          }}
          onClose={() => setExportDrawerFormat(null)}
        />

        {/* Right rail: Your book + Translate — nothing else. */}
        <aside className="w-full shrink-0 space-y-4 border-t-[2px] border-ink-black bg-pulp-paper p-3 md:w-[240px] md:overflow-y-auto md:border-l-[2px] md:border-t-0">

          {/* Your book */}
          <div className="border-[2px] border-ink-black bg-surface-container p-3 shadow-ink-sm">
            <div className="mb-1 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">READY TO PRINT</div>
            <div className="mb-1 font-display text-[1.15rem] font-black uppercase leading-none tracking-[-0.02em] [font-stretch:75%]">Ship your issue</div>
            <div className="mb-3 font-body text-[0.82rem] font-semibold leading-5 text-ink-black/70">
              {pageList.length} page{pageList.length !== 1 ? "s" : ""} · {totalPanels} panel{totalPanels !== 1 ? "s" : ""} · {totalLettering} lettering item{totalLettering !== 1 ? "s" : ""}
            </div>
            <div className="space-y-1.5">
              <Button size="sm" fullWidth onClick={() => handleExportClick("pdf")} disabled={isExporting}>
                {isExporting ? "EXPORTING…" : "↓ DOWNLOAD PDF"}
              </Button>
              <Button size="sm" variant="secondary" fullWidth onClick={() => handleExportClick("cbz")} disabled={isExporting}>
                ↓ CBZ
              </Button>
            </div>
          </div>

          {/* Translate the book — the only home for translation. */}
          <div className="border-[2px] border-ink-black bg-surface-container p-3 shadow-ink-sm">
            <div className="mb-2 font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/50">TRANSLATE THE BOOK</div>
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
              {isTranslatingBubbles ? "TRANSLATING…" : "TRANSLATE ALL"}
            </Button>
            <p className="mt-2 font-meta text-[0.46rem] leading-4 tracking-[0.08em] text-ink-black/40">
              VISUAL STYLE LIVES AT THE LOOK STATION — CHANGING IT RE-RENDERS THE BOOK.
            </p>
          </div>
        </aside>
      </div>
    </div>
  );
}

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
  const [zoom, setZoom] = useState(1);

  const pageCount = leftSummary && rightSummary ? 2 : 1;
  const nativeW = PAGE_W * pageCount;

  if (isLoading) {
    return (
      <div className="flex min-w-0 flex-1 items-center justify-center">
        <p className="font-meta text-[0.6rem] tracking-[0.2em] text-ink-black/40">LOADING PREVIEW...</p>
      </div>
    );
  }

  return (
    <div className="min-w-0 flex-1 overflow-hidden">
      <ScaledContainer
        zoom={zoom}
        onZoomChange={setZoom}
        nativeW={nativeW}
        nativeH={PAGE_H}
        maxZoom={3}
        fitPadding={64}
      >
        <div className="flex shadow-ink-lg" style={{ width: nativeW, height: PAGE_H }}>
          {leftSummary && <PreviewPageSheet project={project} summary={leftSummary} isLeft />}
          {rightSummary && <PreviewPageSheet project={project} summary={rightSummary} isLeft={false} />}
        </div>
      </ScaledContainer>
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

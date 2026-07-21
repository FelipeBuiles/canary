import { useState } from "react";
import type { ComicPage, LetteringStyle, PageSummary } from "../../types/api";
import { Button } from "../ui/Button";
import { ConfirmDrawer } from "../composites";
import { cn } from "../../lib/cn";
import type { ComposeIssue } from "../../lib/issueEngine";
import { ScaledContainer } from "./ScaledContainer";
import { PAGE_W, PAGE_H } from "./layouts";
import { ComicPageCanvas } from "./ComicPageCanvas";

const LANGUAGES = [
  { value: "en" as const, label: "English" },
  { value: "es" as const, label: "Español" },
  { value: "fr" as const, label: "Français" },
];

interface PreviewModeProps {
  project: string;
  pages: (ComicPage | undefined)[];
  pageList: PageSummary[];
  lettering?: LetteringStyle;
  isLoading: boolean;
  pageIdx: number;
  isExporting: boolean;
  outputLanguage: "en" | "es" | "fr";
  isTranslatingBubbles: boolean;
  exportError: string | null;
  issues: ComposeIssue[];
  onPageSelect: (idx: number) => void;
  onExport: (format: "pdf" | "cbz", allowIssues?: boolean) => void;
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
  lettering,
  isLoading,
  pageIdx,
  isExporting,
  outputLanguage,
  isTranslatingBubbles,
  exportError,
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
  const leftPage = leftSummary
    ? pages.find((page) => page?.page_number === leftSummary.page_number)
    : undefined;
  const rightPage = rightSummary
    ? pages.find((page) => page?.page_number === rightSummary.page_number)
    : undefined;

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
          <div className="font-display text-[1.4rem] font-black uppercase leading-none tracking-[-0.035em]">
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
            leftPage={leftPage}
            rightPage={rightPage}
            lettering={lettering}
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
            if (exportDrawerFormat) onExport(exportDrawerFormat, true);
            setExportDrawerFormat(null);
          }}
          onClose={() => setExportDrawerFormat(null)}
        />

        {/* Right rail: one compact colophon for shipping and translation. */}
        <aside className="w-full shrink-0 border-t-[2px] border-ink-black bg-pulp-paper p-3 md:w-[250px] md:overflow-y-auto md:border-l-[2px] md:border-t-0">
          <div className="border-[3px] border-ink-black bg-bristol shadow-paper-sm">
            <section className="p-4">
              <div className="mb-1 bg-narrator-gold px-2 py-1 font-meta text-[0.56rem] font-bold tracking-[0.08em] text-ink-black">READY TO PRINT</div>
              <div className="mb-1 font-display text-[1.2rem] font-black uppercase leading-none tracking-[-0.02em]">Ship your issue</div>
              <div className="mb-4 font-body text-[0.82rem] font-semibold leading-5 text-ink-muted">
                {pageList.length} page{pageList.length !== 1 ? "s" : ""} · {totalPanels} panel{totalPanels !== 1 ? "s" : ""} · {totalLettering} lettering item{totalLettering !== 1 ? "s" : ""}
              </div>
              <div className="space-y-2">
                {exportError && (
                  <p role="alert" className="border-[2px] border-hero-red bg-chip-red/40 px-2 py-1.5 font-body text-[0.72rem] font-semibold leading-snug text-hero-red">
                    {exportError}
                  </p>
                )}
                <Button size="sm" fullWidth onClick={() => handleExportClick("pdf")} disabled={isExporting}>
                  {isExporting ? "EXPORTING…" : "↓ DOWNLOAD PDF"}
                </Button>
                <Button size="sm" variant="secondary" fullWidth onClick={() => handleExportClick("cbz")} disabled={isExporting}>
                  ↓ CBZ
                </Button>
              </div>
            </section>

            <section className="border-t-[3px] border-ink-black bg-surface-container p-4">
              <div className="mb-3 font-meta text-[0.58rem] font-bold tracking-[0.08em] text-ink-muted">TRANSLATE THE BOOK</div>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {LANGUAGES.map((lang) => (
                  <button
                    key={lang.value}
                    onClick={() => onOutputLanguageChange(lang.value)}
                    disabled={isTranslatingBubbles}
                    className={cn(
                      "min-h-9 border-[2px] border-ink-black px-2 py-1 font-meta text-[0.54rem] font-bold tracking-[0.06em] transition-colors disabled:opacity-50",
                      outputLanguage === lang.value
                        ? "bg-ink-black text-pulp-paper"
                        : "bg-pulp-paper hover:bg-bristol",
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
              <p className="mt-3 font-body text-[0.68rem] font-semibold leading-4 text-ink-muted">
                Visual style lives at the Look station. Changing it re-renders the book.
              </p>
            </section>
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
  leftPage,
  rightPage,
  lettering,
}: {
  project: string;
  isLoading: boolean;
  leftSummary: PageSummary | undefined;
  rightSummary: PageSummary | undefined;
  leftPage: ComicPage | undefined;
  rightPage: ComicPage | undefined;
  lettering?: LetteringStyle;
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
          {leftSummary && (
            <PreviewPageSheet
              project={project}
              summary={leftSummary}
              page={leftPage}
              lettering={lettering}
              isLeft
            />
          )}
          {rightSummary && (
            <PreviewPageSheet
              project={project}
              summary={rightSummary}
              page={rightPage}
              lettering={lettering}
              isLeft={false}
            />
          )}
        </div>
      </ScaledContainer>
    </div>
  );
}

function PreviewPageSheet({
  project,
  summary,
  page,
  lettering,
  isLeft,
}: {
  project: string;
  summary: PageSummary;
  page: ComicPage | undefined;
  lettering?: LetteringStyle;
  isLeft: boolean;
}) {
  const imageBaseUrl = `/api/projects/${encodeURIComponent(project)}/files`;
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
      {page ? (
        <div
          aria-label={`Page ${summary.page_number} preview`}
          className="pointer-events-none"
          style={{ width: PAGE_W, height: PAGE_H }}
        >
          <ComicPageCanvas
            page={page}
            lettering={lettering}
            selectedPanelId={null}
            selectedElementId={null}
            selectedType={null}
            reframePanelId={null}
            imageBaseUrl={imageBaseUrl}
          />
        </div>
      ) : (
        <div
          className="flex h-full w-full items-center justify-center font-meta text-[2rem] tracking-[0.18em] text-ink-black/40"
        >
          LOADING PAGE {summary.page_number}…
        </div>
      )}
    </div>
  );
}

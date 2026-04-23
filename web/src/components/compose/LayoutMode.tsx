import { useEffect, useMemo, useRef, useState } from "react";
import type { ComicPage, Bubble, Sfx, PageSummary, PagePanel } from "../../types/api";
import { PageNavigator } from "./PageNavigator";
import { EditorToolbar } from "./EditorToolbar";
import { PageEditor } from "./PageEditor";
import { PropertyPanel } from "./PropertyPanel";
import { cn } from "../../lib/cn";

interface LayoutModeProps {
  project: string;
  pageList: PageSummary[];
  page: ComicPage | undefined;
  pageNumber: number;
  isLoadingPage: boolean;
  zoom: number;
  selection: { panelId: string; type: "bubble" | "sfx"; elementId: string } | null;
  undoStack: ComicPage[];
  redoStack: ComicPage[];
  isGeneratingPageStyle: boolean;
  isTranslatingBubbles: boolean;
  outputLanguage: "en" | "es" | "fr";
  onPageSelect: (pageNum: number) => void;
  onAddBubble: (type: "speech" | "thought" | "narration") => void;
  onAddSfx: () => void;
  onDelete: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onTryLayouts: () => void;
  onSelect: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onDeselect: () => void;
  onDragEnd: (
    panelId: string,
    type: "bubble" | "sfx",
    elementId: string,
    x: number,
    y: number,
  ) => void;
  onZoomChange: (z: number) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomReset: () => void;
  onUpdatePanel: (panelId: string, patch: Partial<PagePanel>) => void;
  onUpdatePanelStructure: (
    plannedPanelId: string,
    patch: { importance?: string | null; shape_intent?: string | null; generation_mode?: string | null },
  ) => void;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onUpdateSfx: (panelId: string, patch: Partial<Sfx>) => void;
  onUpdatePage: (patch: Partial<ComicPage>) => void;
  onReflowPages: (panelsPerPage: number) => void;
  onGeneratePageStyle: () => void;
  onOutputLanguageChange: (lang: "en" | "es" | "fr") => void;
  onTranslateBubbles: (lang: "en" | "es" | "fr") => void;
  onDeleteElement: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onUnpin: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  inspectorMode: "floating" | "fixed";
  onInspectorModeChange: (mode: "floating" | "fixed") => void;
}

export function LayoutMode({
  project,
  pageList,
  page,
  pageNumber,
  isLoadingPage,
  zoom,
  selection,
  undoStack,
  redoStack,
  isGeneratingPageStyle,
  isTranslatingBubbles,
  outputLanguage,
  onPageSelect,
  onAddBubble,
  onAddSfx,
  onDelete,
  onUndo,
  onRedo,
  onTryLayouts,
  onSelect,
  onDeselect,
  onDragEnd,
  onZoomChange,
  onZoomIn,
  onZoomOut,
  onZoomReset,
  onUpdatePanel,
  onUpdatePanelStructure,
  onUpdateBubble,
  onUpdateSfx,
  onUpdatePage,
  onReflowPages,
  onGeneratePageStyle,
  onOutputLanguageChange,
  onTranslateBubbles,
  onDeleteElement,
  onUnpin,
  inspectorMode,
  onInspectorModeChange,
}: LayoutModeProps) {
  const canvasShellRef = useRef<HTMLElement>(null);
  const [floatingPosition, setFloatingPosition] = useState<{ top: number; left: number } | null>(null);

  useEffect(() => {
    if (inspectorMode !== "floating" || !selection) {
      setFloatingPosition(null);
      return;
    }

    const updatePosition = () => {
      const shell = canvasShellRef.current;
      if (!shell) return;

      const selector =
        selection.type === "bubble"
          ? `[data-id="${CSS.escape(selection.elementId)}"]`
          : `[data-sfx="${CSS.escape(selection.panelId)}"]`;
      const target = shell.querySelector<HTMLElement>(selector);
      if (!target) {
        setFloatingPosition(null);
        return;
      }

      const shellRect = shell.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const inspectorWidth = 320;
      const gap = 16;
      let left = targetRect.right - shellRect.left + gap;
      const maxLeft = Math.max(gap, shellRect.width - inspectorWidth - gap);
      if (left > maxLeft) {
        left = Math.max(gap, targetRect.left - shellRect.left - inspectorWidth - gap);
      }
      const top = Math.min(
        Math.max(gap, targetRect.top - shellRect.top),
        Math.max(gap, shellRect.height - 420),
      );
      setFloatingPosition({ top, left });
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    return () => window.removeEventListener("resize", updatePosition);
  }, [inspectorMode, selection, page, zoom]);

  const propertyPanel = useMemo(() => {
    if (!page) return null;
    return (
      <PropertyPanel
        page={page}
        selection={selection}
        onUpdatePanel={onUpdatePanel}
        onUpdatePanelStructure={onUpdatePanelStructure}
        onUpdateBubble={onUpdateBubble}
        onUpdateSfx={onUpdateSfx}
        onUpdatePage={onUpdatePage}
        onReflowPages={onReflowPages}
        onGeneratePageStyle={onGeneratePageStyle}
        outputLanguage={outputLanguage}
        onOutputLanguageChange={onOutputLanguageChange}
        onTranslateBubbles={onTranslateBubbles}
        isGeneratingPageStyle={isGeneratingPageStyle}
        isTranslatingBubbles={isTranslatingBubbles}
        onDeleteElement={onDeleteElement}
        onUnpin={onUnpin}
      />
    );
  }, [
    isGeneratingPageStyle,
    isTranslatingBubbles,
    onDeleteElement,
    onGeneratePageStyle,
    onOutputLanguageChange,
    onReflowPages,
    onTranslateBubbles,
    onUnpin,
    onUpdateBubble,
    onUpdatePage,
    onUpdatePanel,
    onUpdateSfx,
    outputLanguage,
    page,
    selection,
  ]);

  const selectedBubble = selection?.type === "bubble" && page
    ? page.panels
        .find((panel) => panel.id === selection.panelId)
        ?.bubbles.find((bubble) => bubble.id === selection.elementId) ?? null
    : null;
  const panelCount = page?.panels.length ?? 0;
  const bubbleCount = page?.panels.reduce((sum, panel) => sum + panel.bubbles.length, 0) ?? 0;
  const sfxCount = page?.panels.reduce((sum, panel) => sum + (panel.sfx ? 1 : 0), 0) ?? 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      {/* Toolbar */}
      <div className="shrink-0 border-b-[2px] border-ink-black px-3 py-2 md:px-4">
        <div className="flex items-center justify-between gap-3">
          <EditorToolbar
            onAddBubble={onAddBubble}
            onAddSfx={onAddSfx}
            onDelete={onDelete}
            onUndo={onUndo}
            onRedo={onRedo}
            onTryLayouts={onTryLayouts}
            onSelectNarration={() => {
              const narration = page?.panels.flatMap((panel) =>
                panel.bubbles
                  .filter((bubble) => bubble.type === "narration")
                  .map((bubble) => ({ panelId: panel.id, bubbleId: bubble.id }))
              )[0];
              if (narration) onSelect(narration.panelId, "bubble", narration.bubbleId);
            }}
            onSelectBySpeaker={() => {
              if (!selectedBubble?.speaker_id || !page) return;
              const matched = page.panels.flatMap((panel) =>
                panel.bubbles
                  .filter((bubble) => bubble.speaker_id === selectedBubble.speaker_id)
                  .map((bubble) => ({ panelId: panel.id, bubbleId: bubble.id }))
              )[0];
              if (matched) onSelect(matched.panelId, "bubble", matched.bubbleId);
            }}
            hasSelection={!!selection}
            canUndo={undoStack.length > 0}
            canRedo={redoStack.length > 0}
            zoomPercent={zoom * 100}
            selectedSpeakerLabel={selectedBubble?.speaker_name ?? null}
            panelCount={panelCount}
            bubbleCount={bubbleCount}
            sfxCount={sfxCount}
            onZoomIn={onZoomIn}
            onZoomOut={onZoomOut}
            onZoomReset={onZoomReset}
          />
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              onClick={() => onInspectorModeChange("floating")}
              className={cn(
                "border-[2px] px-2 py-1 font-meta text-[0.52rem] tracking-[0.12em]",
                inspectorMode === "floating"
                  ? "border-ink-black bg-ink-black text-pulp-paper"
                  : "border-ink-black bg-pulp-paper",
              )}
            >
              FLOATING
            </button>
            <button
              type="button"
              onClick={() => onInspectorModeChange("fixed")}
              className={cn(
                "border-[2px] px-2 py-1 font-meta text-[0.52rem] tracking-[0.12em]",
                inspectorMode === "fixed"
                  ? "border-ink-black bg-ink-black text-pulp-paper"
                  : "border-ink-black bg-pulp-paper",
              )}
            >
              FIXED
            </button>
          </div>
        </div>
      </div>

      {/* 3-column layout */}
      <div
        className={cn(
          "grid min-h-0 flex-1 grid-cols-[180px_minmax(0,1fr)] gap-3 overflow-hidden p-3 md:p-4",
          inspectorMode === "fixed" && "xl:grid-cols-[220px_minmax(0,1fr)_340px]",
        )}
      >
        {/* Left: page navigator */}
        <aside className="min-h-0 min-w-0 overflow-y-auto">
          <PageNavigator
            project={project}
            pages={pageList}
            currentPage={pageNumber}
            onSelect={onPageSelect}
          />
        </aside>

        {/* Center: canvas */}
        <section
          ref={canvasShellRef}
          className="relative min-h-[560px] min-w-0 overflow-hidden border-[2px] border-ink-black bg-[radial-gradient(circle_at_1px_1px,rgba(27,28,21,0.12)_1px,transparent_0)] p-2 shadow-[6px_6px_0_0_var(--color-ghost-shadow)] [background-size:18px_18px] md:min-h-0 md:p-4"
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <div>
              <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45">
                PAGE BENCH
              </div>
              <div className="font-display text-[1.1rem] font-bold leading-none tracking-[-0.02em] text-ink-black">
                Page {String(pageNumber).padStart(2, "0")}
              </div>
            </div>
            <div className="hidden font-meta text-[0.52rem] tracking-[0.16em] text-ink-black/45 sm:block">
              {page?.panels.length ?? 0} PANELS
            </div>
          </div>
          <div className="h-[72vh] min-h-[480px] overflow-hidden border-[2px] border-ink-black bg-pulp-paper/90 p-2 md:h-[calc(100vh-390px)] md:min-h-0">
            {isLoadingPage ? (
              <div
                className="flex h-full items-center justify-center bg-ink-black/5"
                style={{ aspectRatio: "2480 / 3508", maxHeight: "100%" }}
              >
                <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">
                  LOADING PAGE...
                </p>
              </div>
            ) : page ? (
              <PageEditor
                page={page}
                project={project}
                zoom={zoom}
                onZoomChange={onZoomChange}
                selectedId={selection?.elementId ?? null}
                selectedType={selection?.type ?? null}
                onSelect={onSelect}
                onDeselect={onDeselect}
                onDragEnd={onDragEnd}
              />
            ) : null}
          </div>

          {inspectorMode === "floating" && selection && propertyPanel && floatingPosition && (
            <div
              className="absolute z-20 w-[320px] max-w-[calc(100%-2rem)]"
              style={{ top: floatingPosition.top, left: floatingPosition.left }}
            >
              <div className="[&_.shadow-ink-sm]:shadow-none [&_.shadow-ink]:shadow-none [&_.shadow-ink-lg]:shadow-none">
                {propertyPanel}
              </div>
            </div>
          )}
        </section>

        {inspectorMode === "fixed" && (
          <aside className="min-h-0 min-w-0 overflow-y-auto xl:block">
            {propertyPanel}
          </aside>
        )}
      </div>
    </div>
  );
}

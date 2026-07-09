import { useEffect, useMemo, useRef, useState } from "react";
import type { ComicPage, Bubble, Sfx, PageSummary, PagePanel } from "../../types/api";
import { PageNavigator } from "./PageNavigator";
import { EditorToolbar } from "./EditorToolbar";
import { PageEditor } from "./PageEditor";
import { PropertyPanel } from "./PropertyPanel";
import { useLetteringStyle } from "../../api/queries";

interface LayoutModeProps {
  project: string;
  pageList: PageSummary[];
  page: ComicPage | undefined;
  pageNumber: number;
  isLoadingPage: boolean;
  zoom: number;
  selection: { panelId: string; type: "bubble" | "sfx"; elementId: string } | null;
  panelReframeId: string | null;
  canUndo: boolean;
  canRedo: boolean;
  onPageSelect: (pageNum: number) => void;
  onAddBubble: (type: "speech" | "thought" | "narration") => void;
  onAddSfx: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onSelect: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onDeselect: () => void;
  onDragEnd: (panelId: string, type: "bubble" | "sfx", elementId: string, x: number, y: number) => void;
  onZoomChange: (z: number) => void;
  onUpdatePanel: (panelId: string, patch: Partial<PagePanel>) => void;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onUpdateSfx: (panelId: string, sfxIndex: number, patch: Partial<Sfx>) => void;
  onPanelReframeStart: (panelId: string) => void;
  onPanelReframeDragEnd: (panelId: string, newOffsetX: number, newOffsetY: number) => void;
  onResetPanelFrame: (panelId: string) => void;
  onDeleteElement: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onUnpin: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  /** Re-fetch missing page thumbnails while compose is still rendering. */
  shouldRetryThumbs?: boolean;
}

export function LayoutMode({
  project,
  pageList,
  page,
  pageNumber,
  isLoadingPage,
  zoom,
  selection,
  panelReframeId,
  canUndo,
  canRedo,
  onPageSelect,
  onAddBubble,
  onAddSfx,
  onUndo,
  onRedo,
  onSelect,
  onDeselect,
  onDragEnd,
  onZoomChange,
  onUpdateBubble,
  onUpdateSfx,
  onPanelReframeStart,
  onPanelReframeDragEnd,
  onResetPanelFrame,
  onDeleteElement,
  onUnpin,
  shouldRetryThumbs,
}: LayoutModeProps) {
  const { data: lettering } = useLetteringStyle(project);
  const canvasShellRef = useRef<HTMLElement>(null);
  const [floatingPosition, setFloatingPosition] = useState<{ top: number; left: number; shellViewportTop: number } | null>(null);
  const [dragOffset, setDragOffset] = useState({ dx: 0, dy: 0 });
  const dragStartRef = useRef<{ clientX: number; clientY: number; dx: number; dy: number } | null>(null);

  useEffect(() => {
    setDragOffset({ dx: 0, dy: 0 });
  }, [selection?.elementId, panelReframeId]);

  useEffect(() => {
    const hasInspector = !!selection || !!panelReframeId;
    if (!hasInspector) {
      setFloatingPosition(null);
      return;
    }

    const updatePosition = () => {
      const shell = canvasShellRef.current;
      if (!shell) return;

      // Find anchor element: bubble/sfx element, or the panel itself for reframe
      let selector: string | null = null;
      if (selection?.type === "bubble") {
        selector = `[data-id="${CSS.escape(selection.elementId)}"]`;
      } else if (selection?.type === "sfx") {
        // Anchor to the selected SFX, not just the panel's first one.
        const sfxIndexMatch = selection.elementId.match(/__sfx__(\d+)$/);
        const sfxIndex = sfxIndexMatch ? sfxIndexMatch[1] : "0";
        selector = `[data-sfx="${CSS.escape(selection.panelId)}"][data-sfx-index="${sfxIndex}"]`;
      } else if (panelReframeId) {
        selector = `[data-panel-id="${CSS.escape(panelReframeId)}"]`;
      }
      if (!selector) { setFloatingPosition(null); return; }

      const target = shell.querySelector<HTMLElement>(selector);
      if (!target) { setFloatingPosition(null); return; }

      const shellRect = shell.getBoundingClientRect();
      const targetRect = target.getBoundingClientRect();
      const inspectorWidth = 300;
      const gap = 16;
      const estimatedHeight = 450;

      const panelEl = target.closest<HTMLElement>("[data-panel-id]") ?? target;
      const panelRect = panelEl.getBoundingClientRect();

      let left: number;
      const rightOfPanel = panelRect.right - shellRect.left + gap;
      const leftOfPanel = panelRect.left - shellRect.left - inspectorWidth - gap;

      if (rightOfPanel + inspectorWidth <= shellRect.width - gap) {
        left = rightOfPanel;
      } else if (leftOfPanel >= gap) {
        left = leftOfPanel;
      } else {
        left = Math.max(gap, targetRect.right - shellRect.left + gap);
      }

      const viewportH = window.innerHeight;
      const bubbleTopInShell = targetRect.top - shellRect.top;
      const spaceBelow = viewportH - targetRect.bottom - gap;
      const spaceAbove = targetRect.top - gap;

      let top: number;

      if (spaceBelow >= estimatedHeight) {
        top = Math.max(gap, bubbleTopInShell);
      } else if (spaceAbove >= estimatedHeight) {
        top = Math.max(gap, bubbleTopInShell - estimatedHeight);
      } else if (spaceBelow >= spaceAbove) {
        top = Math.max(gap, bubbleTopInShell);
      } else {
        top = Math.max(gap, bubbleTopInShell - spaceAbove);
      }

      setFloatingPosition({ top, left, shellViewportTop: shellRect.top });
    };

    updatePosition();
    window.addEventListener("resize", updatePosition);
    return () => window.removeEventListener("resize", updatePosition);
  }, [selection, panelReframeId, page, zoom]);

  const propertyPanel = useMemo(() => {
    if (!page) return null;
    return (
      <PropertyPanel
        page={page}
        selection={selection}
        panelReframeId={panelReframeId}
        onUpdateBubble={onUpdateBubble}
        onUpdateSfx={onUpdateSfx}
        onDeleteElement={onDeleteElement}
        onUnpin={onUnpin}
        onResetPanelFrame={onResetPanelFrame}
      />
    );
  }, [page, selection, panelReframeId, onUpdateBubble, onUpdateSfx, onDeleteElement, onUnpin, onResetPanelFrame]);

  const hasInspector = !!selection || !!panelReframeId;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
      <div className="shrink-0 border-b-[2px] border-ink-black bg-pulp-paper px-3 py-2 md:px-4">
        <EditorToolbar
          onAddBubble={onAddBubble}
          onAddSfx={onAddSfx}
          onUndo={onUndo}
          onRedo={onRedo}
          canUndo={canUndo}
          canRedo={canRedo}
        />
      </div>

      <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto bg-pulp-paper px-2 pb-3 pt-3 md:grid md:grid-cols-[154px_minmax(0,1fr)] md:overflow-hidden">
        <aside className="min-h-0 min-w-0 shrink-0 md:overflow-y-auto">
          <PageNavigator
            project={project}
            pages={pageList}
            currentPage={pageNumber}
            onSelect={onPageSelect}
            shouldRetryThumbs={shouldRetryThumbs}
          />
        </aside>

        <section
          ref={canvasShellRef}
          className="relative flex min-h-[560px] min-w-0 flex-col overflow-hidden border-[3px] border-ink-black bg-pulp-paper p-3 shadow-[4px_4px_0_0_var(--color-ink-black)] md:min-h-0 md:p-4"
        >
          <div className="mb-2">
            <div className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/45">PAGE BENCH</div>
            <div className="font-display text-[1.1rem] font-bold leading-none tracking-[-0.02em]">
              Page {String(pageNumber).padStart(2, "0")}
            </div>
          </div>

          <div className="h-[72vh] min-h-[480px] overflow-hidden border-[2px] border-ink-black bg-bristol p-2 md:h-auto md:min-h-0 md:flex-1">
            {isLoadingPage ? (
              <div className="flex h-full items-center justify-center bg-ink-black/5" style={{ aspectRatio: "2480 / 3508", maxHeight: "100%" }}>
                <p className="font-meta text-sm tracking-[0.28em] text-ink-black/40">LOADING PAGE...</p>
              </div>
            ) : page ? (
              <PageEditor
                page={page}
                lettering={lettering}
                project={project}
                zoom={zoom}
                onZoomChange={onZoomChange}
                selectedId={selection?.elementId ?? null}
                selectedType={selection?.type ?? null}
                reframePanelId={panelReframeId}
                onSelect={onSelect}
                onDeselect={onDeselect}
                onPanelReframeStart={onPanelReframeStart}
                onPanelReframeDragEnd={onPanelReframeDragEnd}
                onDragEnd={onDragEnd}
              />
            ) : null}
          </div>

          {/* Floating inspector */}
          {hasInspector && propertyPanel && floatingPosition && (() => {
            const gap = 16;
            const currentTop = Math.max(gap, floatingPosition.top + dragOffset.dy);
            const dynamicMaxHeight = Math.max(
              140,
              window.innerHeight - floatingPosition.shellViewportTop - currentTop - gap,
            );

            return (
            <div
              className="absolute z-[200] flex w-[300px] max-w-[calc(100%-2rem)] flex-col overflow-hidden"
              style={{
                top: currentTop,
                left: floatingPosition.left + dragOffset.dx,
                maxHeight: dynamicMaxHeight,
              }}
            >
              <div
                className="flex shrink-0 cursor-grab items-center justify-center border-[2px] border-b-0 border-ink-black bg-pulp-paper py-1.5 select-none active:cursor-grabbing"
                onPointerDown={(e) => {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  dragStartRef.current = { clientX: e.clientX, clientY: e.clientY, dx: dragOffset.dx, dy: dragOffset.dy };
                }}
                onPointerMove={(e) => {
                  if (!dragStartRef.current) return;
                  setDragOffset({
                    dx: dragStartRef.current.dx + (e.clientX - dragStartRef.current.clientX),
                    dy: dragStartRef.current.dy + (e.clientY - dragStartRef.current.clientY),
                  });
                }}
                onPointerUp={() => { dragStartRef.current = null; }}
              >
                <svg width="24" height="8" viewBox="0 0 24 8" className="text-ink-black/60">
                  <circle cx="4" cy="2" r="1.5" fill="currentColor"/>
                  <circle cx="12" cy="2" r="1.5" fill="currentColor"/>
                  <circle cx="20" cy="2" r="1.5" fill="currentColor"/>
                  <circle cx="4" cy="6" r="1.5" fill="currentColor"/>
                  <circle cx="12" cy="6" r="1.5" fill="currentColor"/>
                  <circle cx="20" cy="6" r="1.5" fill="currentColor"/>
                </svg>
              </div>
              <div className="overflow-y-auto [&_.shadow-ink-sm]:shadow-none [&_.shadow-ink]:shadow-none">
                {propertyPanel}
              </div>
            </div>
            );
          })()}
        </section>
      </div>
    </div>
  );
}

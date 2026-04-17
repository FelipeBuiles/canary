import { useCallback, useRef, useState } from "react";
import type { ComicPage } from "../../types/api";
import { ScaledContainer } from "./ScaledContainer";
import { ComicPageCanvas } from "./ComicPageCanvas";
import { exceedsThreshold } from "./coordinates";

interface PageEditorProps {
  page: ComicPage;
  project: string;
  selectedId: string | null;
  selectedType: "bubble" | "sfx" | null;
  onSelect: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onDeselect: () => void;
  onDragEnd?: (
    panelId: string,
    type: "bubble" | "sfx",
    elementId: string,
    x: number,
    y: number,
  ) => void;
}

interface DragState {
  panelId: string;
  type: "bubble" | "sfx";
  elementId: string;
  startClientX: number;
  startClientY: number;
  startPanelX: number;
  startPanelY: number;
  scale: number;
}

interface DragPreview extends DragState {
  dx: number;
  dy: number;
}

/** Find the closest ancestor (or self) matching a selector */
function closest(el: HTMLElement | null, sel: string): HTMLElement | null {
  return el?.closest(sel) ?? null;
}

/**
 * Main editor surface — replaces PagePreview + EditorOverlay.
 * Renders the comic page natively in React with event delegation for selection and drag.
 */
export function PageEditor({
  page,
  project,
  selectedId,
  selectedType,
  onSelect,
  onDeselect,
  onDragEnd,
}: PageEditorProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const scaleRef = useRef(0);
  const dragRef = useRef<DragState | null>(null);
  const [dragPreview, setDragPreview] = useState<DragPreview | null>(null);

  const imageBaseUrl = `/api/projects/${encodeURIComponent(project)}/files`;

  const handleScaleChange = useCallback((s: number) => {
    scaleRef.current = s;
  }, []);

  // ── Event delegation: single handler for all pointer events ──

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      const target = e.target as HTMLElement;

      // 1) Check if a bubble was clicked (data-id on .bubble or .caption)
      const bubbleEl = closest(target, "[data-id][data-editor-selectable]");
      if (bubbleEl) {
        const bubbleId = bubbleEl.getAttribute("data-id")!;
        const panelEl = closest(bubbleEl, "[data-panel-id]");
        const panelId = panelEl?.getAttribute("data-panel-id");
        if (!panelId) return;

        onSelect(panelId, "bubble", bubbleId);

        // Initiate drag
        if (onDragEnd) {
          const canvas = canvasRef.current;
          const scale = scaleRef.current;
          if (canvas && panelEl && scale) {
            const startPos = getVisualPanelPosition(bubbleEl, panelEl, scale);
            const dragState: DragState = {
              panelId,
              type: "bubble",
              elementId: bubbleId,
              startClientX: e.clientX,
              startClientY: e.clientY,
              startPanelX: startPos.x,
              startPanelY: startPos.y,
              scale,
            };
            dragRef.current = dragState;
            setDragPreview({ ...dragState, dx: 0, dy: 0 });
            canvas.setPointerCapture(e.pointerId);
          }
        }
        return;
      }

      // 2) Check if SFX was clicked (data-sfx on .sfx)
      const sfxEl = closest(target, "[data-sfx][data-editor-selectable]");
      if (sfxEl) {
        const panelId = sfxEl.getAttribute("data-sfx")!;
        const elementId = `${panelId}__sfx`;

        onSelect(panelId, "sfx", elementId);

        // Initiate drag
        if (onDragEnd) {
          const canvas = canvasRef.current;
          const scale = scaleRef.current;
          const panelEl = closest(sfxEl, "[data-panel-id]");
          if (canvas && panelEl && scale) {
            const startPos = getVisualPanelPosition(sfxEl, panelEl, scale);
            const dragState: DragState = {
              panelId,
              type: "sfx",
              elementId,
              startClientX: e.clientX,
              startClientY: e.clientY,
              startPanelX: startPos.x,
              startPanelY: startPos.y,
              scale,
            };
            dragRef.current = dragState;
            setDragPreview({ ...dragState, dx: 0, dy: 0 });
            canvas.setPointerCapture(e.pointerId);
          }
        }
        return;
      }

      // 3) Click on empty area → deselect
      onDeselect();
    },
    [onSelect, onDeselect, onDragEnd],
  );

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    const ds = dragRef.current;
    if (!ds) return;
    const dx = e.clientX - ds.startClientX;
    const dy = e.clientY - ds.startClientY;
    setDragPreview({ ...ds, dx, dy });
  }, []);

  const handlePointerUp = useCallback(
    (e: React.PointerEvent) => {
      const ds = dragRef.current;
      if (!ds || !onDragEnd) {
        dragRef.current = null;
        setDragPreview(null);
        return;
      }

      const dx = e.clientX - ds.startClientX;
      const dy = e.clientY - ds.startClientY;

      if (exceedsThreshold(dx, dy)) {
        onDragEnd(
          ds.panelId,
          ds.type,
          ds.elementId,
          ds.startPanelX + dx / ds.scale,
          ds.startPanelY + dy / ds.scale,
        );
      }

      dragRef.current = null;
      setDragPreview(null);
      if (canvasRef.current?.hasPointerCapture(e.pointerId)) {
        canvasRef.current.releasePointerCapture(e.pointerId);
      }
    },
    [onDragEnd],
  );

  // Build modified page for optimistic drag preview
  const displayPage = dragPreview
    ? applyDragPreview(page, dragPreview)
    : page;

  return (
    <div
      ref={canvasRef}
      className="w-full h-full"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
    >
      <ScaledContainer onScaleChange={handleScaleChange}>
        <ComicPageCanvas
          page={displayPage}
          selectedElementId={selectedId}
          selectedType={selectedType}
          imageBaseUrl={imageBaseUrl}
        />
      </ScaledContainer>
    </div>
  );
}

/** Measure an element's current visual top-left as panel-relative page coordinates. */
function getVisualPanelPosition(
  element: HTMLElement,
  panelEl: HTMLElement,
  scale: number,
): { x: number; y: number } {
  const elementRect = element.getBoundingClientRect();
  const panelRect = panelEl.getBoundingClientRect();

  return {
    x: (elementRect.left - panelRect.left) / scale - panelEl.clientLeft,
    y: (elementRect.top - panelRect.top) / scale - panelEl.clientTop,
  };
}

/** Optimistically apply drag delta to page data for smooth preview */
function applyDragPreview(
  page: ComicPage,
  preview: DragPreview,
): ComicPage {
  const x = preview.startPanelX + preview.dx / preview.scale;
  const y = preview.startPanelY + preview.dy / preview.scale;

  return {
    ...page,
    panels: page.panels.map((panel) => {
      if (preview.type === "bubble" && panel.id === preview.panelId) {
        return {
          ...panel,
          bubbles: panel.bubbles.map((b) =>
            b.id === preview.elementId
              ? { ...b, x, y }
              : b,
          ),
        };
      }

      if (preview.type === "sfx" && panel.id === preview.panelId && panel.sfx) {
        return {
          ...panel,
          sfx: {
            ...panel.sfx,
            x,
            y,
          },
        };
      }

      return panel;
    }),
  };
}

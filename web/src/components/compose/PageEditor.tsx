import { useCallback, useEffect, useRef, useState } from "react";
import type { ComicPage } from "../../types/api";
import { ScaledContainer } from "./ScaledContainer";
import { ComicPageCanvas } from "./ComicPageCanvas";
import { exceedsThreshold } from "./coordinates";

function parseSfxIndexFromId(elementId: string): number {
  const m = elementId.match(/__sfx__(\d+)$/);
  return m ? Number(m[1]) : 0;
}

interface PageEditorProps {
  page: ComicPage;
  project: string;
  zoom: number;
  onZoomChange: (zoom: number) => void;
  selectedId: string | null;
  selectedType: "bubble" | "sfx" | null;
  reframePanelId: string | null;
  onSelect: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onDeselect: () => void;
  onPanelReframeStart: (panelId: string) => void;
  onPanelReframeDragEnd: (panelId: string, newOffsetX: number, newOffsetY: number) => void;
  onDragEnd?: (
    panelId: string,
    type: "bubble" | "sfx",
    elementId: string,
    x: number,
    y: number,
  ) => void;
}

interface ElementDragState {
  panelId: string;
  type: "bubble" | "sfx";
  elementId: string;
  startClientX: number;
  startClientY: number;
  startPanelX: number;
  startPanelY: number;
  scale: number;
}

interface ElementDragPreview extends ElementDragState {
  dx: number;
  dy: number;
}

interface PanelReframeDrag {
  panelId: string;
  startClientX: number;
  startClientY: number;
  startOffsetX: number;
  startOffsetY: number;
  scale: number;
  dx: number;
  dy: number;
}

function closest(el: HTMLElement | null, sel: string): HTMLElement | null {
  return el?.closest(sel) ?? null;
}

export function PageEditor({
  page,
  project,
  zoom,
  onZoomChange,
  selectedId,
  selectedType,
  reframePanelId,
  onSelect,
  onDeselect,
  onPanelReframeStart,
  onPanelReframeDragEnd,
  onDragEnd,
}: PageEditorProps) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const scaleRef = useRef(0);
  const dragRef = useRef<ElementDragState | null>(null);
  const panelDragRef = useRef<PanelReframeDrag | null>(null);
  const [dragPreview, setDragPreview] = useState<ElementDragPreview | null>(null);
  const [panelDragPreview, setPanelDragPreview] = useState<PanelReframeDrag | null>(null);
  // Committed drag state persists the optimistic position until the server responds,
  // preventing the rubberband snap between pointerUp and the next page data update.
  const [committedDrag, setCommittedDrag] = useState<ElementDragPreview | null>(null);
  const [committedPanelDrag, setCommittedPanelDrag] = useState<PanelReframeDrag | null>(null);

  useEffect(() => {
    setCommittedDrag(null);
    setCommittedPanelDrag(null);
  }, [page]);

  const imageBaseUrl = `/api/projects/${encodeURIComponent(project)}/files`;

  const handleScaleChange = useCallback((s: number) => {
    scaleRef.current = s;
  }, []);

  const handlePointerDown = useCallback(
    (e: React.PointerEvent) => {
      const target = e.target as HTMLElement;
      const canvas = canvasRef.current;
      const scale = scaleRef.current;

      // 1) Bubble click
      const bubbleEl = closest(target, "[data-id][data-editor-selectable]");
      if (bubbleEl) {
        const bubbleId = bubbleEl.getAttribute("data-id")!;
        const panelEl = closest(bubbleEl, "[data-panel-id]");
        const panelId = panelEl?.getAttribute("data-panel-id");
        if (!panelId) return;
        onSelect(panelId, "bubble", bubbleId);
        if (onDragEnd && canvas && panelEl && scale) {
          const startPos = getVisualPanelPosition(bubbleEl, panelEl, scale);
          const ds: ElementDragState = {
            panelId,
            type: "bubble",
            elementId: bubbleId,
            startClientX: e.clientX,
            startClientY: e.clientY,
            startPanelX: startPos.x,
            startPanelY: startPos.y,
            scale,
          };
          dragRef.current = ds;
          setDragPreview({ ...ds, dx: 0, dy: 0 });
          canvas.setPointerCapture(e.pointerId);
        }
        return;
      }

      // 2) SFX click
      const sfxEl = closest(target, "[data-sfx][data-editor-selectable]");
      if (sfxEl) {
        const panelId = sfxEl.getAttribute("data-sfx")!;
        const sfxIndex = Number(sfxEl.getAttribute("data-sfx-index") ?? "0");
        const elementId = `${panelId}__sfx__${sfxIndex}`;
        onSelect(panelId, "sfx", elementId);
        if (onDragEnd && canvas && scale) {
          const panelEl = closest(sfxEl, "[data-panel-id]");
          if (panelEl) {
            const startPos = getVisualPanelPosition(sfxEl, panelEl, scale);
            const ds: ElementDragState = {
              panelId,
              type: "sfx",
              elementId,
              startClientX: e.clientX,
              startClientY: e.clientY,
              startPanelX: startPos.x,
              startPanelY: startPos.y,
              scale,
            };
            dragRef.current = ds;
            setDragPreview({ ...ds, dx: 0, dy: 0 });
            canvas.setPointerCapture(e.pointerId);
          }
        }
        return;
      }

      // 3) Panel background click → arm reframe mode; drag only starts if already armed
      const panelEl = closest(target, "[data-panel-id]");
      if (panelEl) {
        const panelId = panelEl.getAttribute("data-panel-id")!;
        const panelData = page.panels.find((p) => p.id === panelId);
        if (reframePanelId === panelId && canvas && scale && panelData) {
          // Already armed for this panel — start the reframe drag
          const pd: PanelReframeDrag = {
            panelId,
            startClientX: e.clientX,
            startClientY: e.clientY,
            startOffsetX: panelData.image_offset_x ?? 0,
            startOffsetY: panelData.image_offset_y ?? 0,
            scale,
            dx: 0,
            dy: 0,
          };
          panelDragRef.current = pd;
          setPanelDragPreview(pd);
          canvas.setPointerCapture(e.pointerId);
        } else {
          // First click — arm reframe mode but don't start drag yet
          onPanelReframeStart(panelId);
        }
        return;
      }

      // 4) Empty canvas → deselect
      onDeselect();
    },
    [onSelect, onDeselect, onPanelReframeStart, onDragEnd, page.panels, reframePanelId],
  );

  const handlePointerMove = useCallback((e: React.PointerEvent) => {
    const ds = dragRef.current;
    if (ds) {
      setDragPreview({ ...ds, dx: e.clientX - ds.startClientX, dy: e.clientY - ds.startClientY });
      return;
    }
    const pd = panelDragRef.current;
    if (pd) {
      setPanelDragPreview({ ...pd, dx: e.clientX - pd.startClientX, dy: e.clientY - pd.startClientY });
    }
  }, []);

  const handlePointerUp = useCallback(
    (e: React.PointerEvent) => {
      const canvas = canvasRef.current;

      // Element drag end
      const ds = dragRef.current;
      if (ds && onDragEnd) {
        const dx = e.clientX - ds.startClientX;
        const dy = e.clientY - ds.startClientY;
        if (exceedsThreshold(dx, dy)) {
          onDragEnd(ds.panelId, ds.type, ds.elementId, ds.startPanelX + dx / ds.scale, ds.startPanelY + dy / ds.scale);
          // Freeze preview at committed position; cleared by the useEffect watching page updates
          setCommittedDrag({ ...ds, dx, dy });
        }
        dragRef.current = null;
        setDragPreview(null);
        if (canvas?.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
        return;
      }
      dragRef.current = null;
      setDragPreview(null);

      // Panel reframe drag end
      const pd = panelDragRef.current;
      if (pd) {
        const dx = e.clientX - pd.startClientX;
        const dy = e.clientY - pd.startClientY;
        if (exceedsThreshold(dx, dy)) {
          onPanelReframeDragEnd(
            pd.panelId,
            pd.startOffsetX + dx / pd.scale,
            pd.startOffsetY + dy / pd.scale,
          );
          setCommittedPanelDrag({ ...pd, dx, dy });
        }
        panelDragRef.current = null;
        setPanelDragPreview(null);
        if (canvas?.hasPointerCapture(e.pointerId)) canvas.releasePointerCapture(e.pointerId);
      }
    },
    [onDragEnd, onPanelReframeDragEnd],
  );

  const displayPage = buildDisplayPage(page, dragPreview ?? committedDrag, panelDragPreview ?? committedPanelDrag);

  const selectedPanelId = selectedId
    ? page.panels.find((panel) =>
        panel.bubbles.some((b) => b.id === selectedId) ||
        (selectedType === "sfx" && selectedId.startsWith(`${panel.id}__sfx`)),
      )?.id ?? null
    : null;

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const target = e.target as HTMLElement;
      const selectable = closest(target, "[data-editor-selectable]");
      if (!selectable) return;
      e.preventDefault();
      const bubbleId = selectable.getAttribute("data-id");
      if (bubbleId) {
        const panelEl = closest(selectable, "[data-panel-id]");
        const panelId = panelEl?.getAttribute("data-panel-id");
        if (panelId) onSelect(panelId, "bubble", bubbleId);
        return;
      }
      const sfxPanelId = selectable.getAttribute("data-sfx");
      if (sfxPanelId) {
        const sfxIndex = Number(selectable.getAttribute("data-sfx-index") ?? "0");
        onSelect(sfxPanelId, "sfx", `${sfxPanelId}__sfx__${sfxIndex}`);
      }
    },
    [onSelect],
  );

  return (
    <div
      ref={canvasRef}
      className="w-full h-full"
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onKeyDown={handleKeyDown}
    >
      <ScaledContainer zoom={zoom} onZoomChange={onZoomChange} onScaleChange={handleScaleChange}>
        <ComicPageCanvas
          page={displayPage}
          selectedPanelId={selectedPanelId}
          selectedElementId={selectedId}
          selectedType={selectedType}
          reframePanelId={reframePanelId}
          imageBaseUrl={imageBaseUrl}
        />
      </ScaledContainer>
    </div>
  );
}

function getVisualPanelPosition(element: HTMLElement, panelEl: HTMLElement, scale: number) {
  const elementRect = element.getBoundingClientRect();
  const panelRect = panelEl.getBoundingClientRect();
  return {
    x: (elementRect.left - panelRect.left) / scale - panelEl.clientLeft,
    y: (elementRect.top - panelRect.top) / scale - panelEl.clientTop,
  };
}

function buildDisplayPage(
  page: ComicPage,
  elementDrag: ElementDragPreview | null,
  panelDrag: PanelReframeDrag | null,
): ComicPage {
  if (!elementDrag && !panelDrag) return page;

  return {
    ...page,
    panels: page.panels.map((panel) => {
      // Optimistic element drag
      if (elementDrag && panel.id === elementDrag.panelId) {
        const x = elementDrag.startPanelX + elementDrag.dx / elementDrag.scale;
        const y = elementDrag.startPanelY + elementDrag.dy / elementDrag.scale;
        if (elementDrag.type === "bubble") {
          return {
            ...panel,
            bubbles: panel.bubbles.map((b) =>
              b.id === elementDrag.elementId ? { ...b, x, y } : b,
            ),
          };
        }
        if (elementDrag.type === "sfx" && panel.sfx.length > 0) {
          const idx = parseSfxIndexFromId(elementDrag.elementId);
          return {
            ...panel,
            sfx: panel.sfx.map((s, i) => (i === idx ? { ...s, x, y } : s)),
          };
        }
      }
      // Optimistic panel reframe drag
      if (panelDrag && panel.id === panelDrag.panelId) {
        return {
          ...panel,
          image_offset_x: Math.round(panelDrag.startOffsetX + panelDrag.dx / panelDrag.scale),
          image_offset_y: Math.round(panelDrag.startOffsetY + panelDrag.dy / panelDrag.scale),
        };
      }
      return panel;
    }),
  };
}

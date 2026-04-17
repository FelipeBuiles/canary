import { useCallback, useEffect, useRef, useState } from "react";
import type { ComicPage } from "../../types/api";
import type { PagePreviewHandle } from "./PagePreview";

export interface ElementRect {
  panelId: string;
  elementType: "bubble" | "sfx";
  elementId: string;
  left: number;
  top: number;
  width: number;
  height: number;
}

interface EditorOverlayProps {
  page: ComicPage;
  previewRef: React.RefObject<PagePreviewHandle | null>;
  selectedId: string | null;
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

export function EditorOverlay({
  page,
  previewRef,
  selectedId,
  onSelect,
  onDeselect,
  onDragEnd,
}: EditorOverlayProps) {
  const [rects, setRects] = useState<ElementRect[]>([]);
  const overlayRef = useRef<HTMLDivElement>(null);
  const dragState = useRef<{
    rect: ElementRect;
    startX: number;
    startY: number;
    offsetX: number;
    offsetY: number;
  } | null>(null);
  const [dragPos, setDragPos] = useState<{ id: string; left: number; top: number } | null>(null);

  const scanElements = useCallback(() => {
    const doc = previewRef.current?.getIframeDoc();
    const scale = previewRef.current?.scaleFactor ?? 1;
    if (!doc || !overlayRef.current) return;

    const pageEl = doc.querySelector(".comic-page");
    if (!pageEl) return;
    const pageRect = pageEl.getBoundingClientRect();

    const result: ElementRect[] = [];

    // Scan panels for bubbles and SFX
    for (const panel of page.panels) {
      const panelEl = doc.querySelector(`[data-panel-id="${panel.id}"]`);
      if (!panelEl) continue;

      // Bubbles
      for (const bubble of panel.bubbles) {
        const el = doc.querySelector(`[data-id="${bubble.id}"]`);
        if (!el) continue;
        const r = el.getBoundingClientRect();
        result.push({
          panelId: panel.id,
          elementType: "bubble",
          elementId: bubble.id,
          left: (r.left - pageRect.left) * scale,
          top: (r.top - pageRect.top) * scale,
          width: r.width * scale,
          height: r.height * scale,
        });
      }

      // SFX
      if (panel.sfx) {
        const sfxEl = panelEl.querySelector("[data-sfx]");
        if (sfxEl) {
          const r = sfxEl.getBoundingClientRect();
          result.push({
            panelId: panel.id,
            elementType: "sfx",
            elementId: `${panel.id}__sfx`,
            left: (r.left - pageRect.left) * scale,
            top: (r.top - pageRect.top) * scale,
            width: r.width * scale,
            height: r.height * scale,
          });
        }
      }
    }

    setRects(result);
  }, [page, previewRef]);

  // Rescan when page data changes (after PATCH + iframe reload)
  useEffect(() => {
    // Small delay to let iframe re-render
    const timer = setTimeout(scanElements, 150);
    return () => clearTimeout(timer);
  }, [page, scanElements]);

  // Also expose scanElements on iframe load via the onLoad callback chain
  useEffect(() => {
    const iframe = previewRef.current?.getIframeDoc()?.defaultView;
    if (!iframe) return;
    // Re-scan after fonts load in the iframe
    const timer = setTimeout(scanElements, 500);
    return () => clearTimeout(timer);
  }, [previewRef, scanElements]);

  function handleOverlayClick(e: React.MouseEvent) {
    if (e.target === overlayRef.current) {
      onDeselect();
    }
  }

  function handleElementPointerDown(
    e: React.PointerEvent,
    rect: ElementRect,
  ) {
    e.stopPropagation();
    e.preventDefault();
    onSelect(rect.panelId, rect.elementType, rect.elementId);

    if (!onDragEnd) return;

    const overlay = overlayRef.current;
    if (!overlay) return;

    dragState.current = {
      rect,
      startX: e.clientX,
      startY: e.clientY,
      offsetX: 0,
      offsetY: 0,
    };
    setDragPos({ id: rect.elementId, left: rect.left, top: rect.top });

    overlay.setPointerCapture(e.pointerId);
  }

  function handlePointerMove(e: React.PointerEvent) {
    if (!dragState.current) return;
    const ds = dragState.current;
    const dx = e.clientX - ds.startX;
    const dy = e.clientY - ds.startY;
    ds.offsetX = dx;
    ds.offsetY = dy;
    setDragPos({
      id: ds.rect.elementId,
      left: ds.rect.left + dx,
      top: ds.rect.top + dy,
    });
  }

  function handlePointerUp(e: React.PointerEvent) {
    if (!dragState.current || !onDragEnd) return;
    const ds = dragState.current;
    const scale = previewRef.current?.scaleFactor ?? 1;

    // Convert screen-space drag delta to page coordinates
    const dx = ds.offsetX / scale;
    const dy = ds.offsetY / scale;

    // We need the panel's position in page coordinates to compute panel-relative position
    const doc = previewRef.current?.getIframeDoc();
    if (doc) {
      const panelEl = doc.querySelector(`[data-panel-id="${ds.rect.panelId}"]`);
      const pageEl = doc.querySelector(".comic-page");
      if (panelEl && pageEl) {
        const panelRect = panelEl.getBoundingClientRect();
        const pageRect = pageEl.getBoundingClientRect();

        // Original element position in page coordinates
        const origLeft = ds.rect.left / scale;
        const origTop = ds.rect.top / scale;

        // New position in page coordinates
        const newPageX = origLeft + dx;
        const newPageY = origTop + dy;

        // Panel position in page coordinates
        const panelX = panelRect.left - pageRect.left;
        const panelY = panelRect.top - pageRect.top;

        // Panel-relative coordinates
        const relX = newPageX - panelX;
        const relY = newPageY - panelY;

        // Only fire if there was meaningful movement (> 3px threshold)
        if (Math.abs(ds.offsetX) > 3 || Math.abs(ds.offsetY) > 3) {
          onDragEnd(ds.rect.panelId, ds.rect.elementType, ds.rect.elementId, relX, relY);
        }
      }
    }

    dragState.current = null;
    setDragPos(null);
    overlayRef.current?.releasePointerCapture(e.pointerId);
  }

  return (
    <div
      ref={overlayRef}
      className="absolute inset-0"
      style={{ pointerEvents: "none" }}
      onClick={handleOverlayClick}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
    >
      {rects.map((rect) => {
        const isSelected = selectedId === rect.elementId;
        const isDragging = dragPos?.id === rect.elementId;
        const left = isDragging ? dragPos.left : rect.left;
        const top = isDragging ? dragPos.top : rect.top;

        return (
          <div
            key={rect.elementId}
            onPointerDown={(e) => handleElementPointerDown(e, rect)}
            className={`absolute cursor-pointer transition-shadow ${
              isSelected
                ? "ring-2 ring-hero-red ring-offset-1"
                : "hover:ring-1 hover:ring-hero-red/50"
            } ${isDragging ? "opacity-80" : ""}`}
            style={{
              left,
              top,
              width: rect.width,
              height: rect.height,
              pointerEvents: "auto",
            }}
          />
        );
      })}
    </div>
  );
}

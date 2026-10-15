import { useEffect, useMemo, useRef, useState, type PointerEvent, type KeyboardEvent, type CSSProperties } from "react";
import { elementRect, renderOverlay, type LetteringElement, type PageLettering, type LetteringStyle, type Rect } from "@lettering-engine";
import { Button } from "../ui/Button";
import { Toolbar } from "../composites/Toolbar";
import { useI18n } from "../../i18n";
interface Props {
  state: PageLettering;
  style: LetteringStyle;
  artUrl: string;
  selected: string | null;
  onArtReady: (url: string | null) => void;
  disabled: boolean;
  select: (id: string | null) => void;
  focusText: () => void;
  begin: () => void;
  preview: (id: string, patch: Partial<LetteringElement>) => void;
  commit: () => void;
  cancel: () => void;
  change: (id: string, patch: Partial<LetteringElement>) => void;
  /** Evidence drawn over the art: faces from the page read and the focused check's mark.
   * ``dragFaces`` show only while a balloon or tail is dragged, so faces are visible no-go areas. */
  guides?: { faces: Array<Rect & { label: string }>; dragFaces?: Array<Rect & { label: string }>; focus: (Rect & { severity: "fix" | "consider" }) | null };
}
interface Drag {
  id: string;
  mode: "move" | "resize" | "tail";
  x: number;
  y: number;
  rect: DOMRect;
  original: LetteringElement;
}
const clamp = (n: number, min: number, max: number) => Math.min(max, Math.max(min, n));
function resizeHandlePosition(element: LetteringElement, aspect: number) {
  const box = elementRect(element), angle = element.rotation * Math.PI / 180;
  const dx = box.width / 2 * element.scale, dy = box.height / 2 * element.scale;
  return {
    x: box.x + box.width / 2 + dx * Math.cos(angle) - dy / aspect * Math.sin(angle),
    y: box.y + box.height / 2 + dx * aspect * Math.sin(angle) + dy * Math.cos(angle),
  };
}
const at = (rect: Rect): CSSProperties => ({ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.width * 100}%`, height: `${rect.height * 100}%` });
export function LetteringCanvas({ state, style, artUrl, selected, disabled, onArtReady, select, focusText, begin, preview, commit, cancel, change, guides }: Props) {
  const { t } = useI18n();
  const viewport = useRef<HTMLDivElement>(null), page = useRef<HTMLDivElement>(null);
  const drag = useRef<Drag | null>(null), pan = useRef<{
    x: number;
    y: number;
    left: number;
    top: number;
  } | null>(null);
  const pending = useRef<{ id: string; patch: Partial<LetteringElement> } | null>(null);
  const [dragging, setDragging] = useState(false);
  const frame = useRef<number | null>(null);
  const overlay = useMemo(() => renderOverlay(state, style), [state, style]);
  useEffect(() => () => {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
  }, []);
  function flushPreview() {
    if (frame.current !== null) cancelAnimationFrame(frame.current);
    frame.current = null;
    const next = pending.current;
    pending.current = null;
    if (next) preview(next.id, next.patch);
  }
  function queuePreview(id: string, patch: Partial<LetteringElement>) {
    pending.current = { id, patch };
    if (frame.current === null) frame.current = requestAnimationFrame(flushPreview);
  }
  const [size, setSize] = useState({ width: 800, height: 670 }), [zoom, setZoom] = useState(1), [panMode, setPanMode] = useState(false);
  const [artFailed, setArtFailed] = useState(false);
  useEffect(() => {
    const target = viewport.current;
    if (!target)
      return;
    const update = () => setSize({ width: target.clientWidth || 800, height: target.clientHeight || 670 });
    update();
    if (typeof ResizeObserver === "undefined")
      return;
    const observer = new ResizeObserver(update);
    observer.observe(target);
    return () => observer.disconnect();
  }, []);
  const width = Math.max(160, Math.min(size.width - 40, (size.height - 40) * state.canvas_aspect_ratio)) * zoom;
  const selectedElement = state.elements.find(e => e.id === selected && !e.hidden);
  // Geometry is pure render data; pointer handlers read refs only on events.
  const resizeHandle = selectedElement ? resizeHandlePosition(selectedElement, state.canvas_aspect_ratio) : null;
  function down(event: PointerEvent<HTMLButtonElement>, element: LetteringElement, mode: Drag["mode"]) {
    if (disabled || panMode || event.button !== 0)
      return;
    event.preventDefault();
    event.stopPropagation();
    select(element.id);
    const rect = page.current?.getBoundingClientRect();
    if (!rect)
      return;
    begin();
    drag.current = { id: element.id, mode, x: event.clientX, y: event.clientY, rect, original: element };
    setDragging(mode !== "resize");
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<HTMLButtonElement>) {
    const current = drag.current;
    if (!current)
      return;
    const dx = (event.clientX - current.x) / current.rect.width, dy = (event.clientY - current.y) / current.rect.height;
    const original = current.original;
    if (current.mode === "move")
      queuePreview(current.id, {
        placement: {
          ...original.placement,
          x: clamp(original.placement.x + dx, 0, 1 - elementRect(original).width), width: Math.min(original.placement.width, 1 - clamp(original.placement.x + dx, 0, 1 - elementRect(original).width)), y: clamp(original.placement.y + dy, 0, 1 - elementRect(original).height), height: Math.min(original.placement.height, 1 - clamp(original.placement.y + dy, 0, 1 - elementRect(original).height))
        }
      });
    else if (current.mode === "resize") {
      const angle = -original.rotation * Math.PI / 180, aspect = state.canvas_aspect_ratio;
      const localX = (dx * Math.cos(angle) - dy / aspect * Math.sin(angle)) / original.scale;
      const localY = (dx * aspect * Math.sin(angle) + dy * Math.cos(angle)) / original.scale;
      queuePreview(current.id, {
        tight_box: false, placement: {
          ...original.placement,
          width: clamp(elementRect(original).width + localX, .045, 1 - original.placement.x),
          height: clamp(elementRect(original).height + localY, .025, 1 - original.placement.y)
        }
      });
    }
    else
      queuePreview(current.id, { tail_target: { x: clamp((event.clientX - current.rect.left) / current.rect.width, 0, 1), y: clamp((event.clientY - current.rect.top) / current.rect.height, 0, 1) } });
  }
  function end() {
    if (drag.current) {
      // Commit the final pointer position even if its frame has not painted yet.
      flushPreview();
      drag.current = null;
      setDragging(false);
      commit();
    }
  }
  function abort() {
    if (drag.current) {
      if (frame.current !== null) cancelAnimationFrame(frame.current);
      frame.current = null;
      pending.current = null;
      drag.current = null;
      setDragging(false);
      cancel();
    }
  }
  function nudge(event: KeyboardEvent<HTMLButtonElement>, element: LetteringElement, mode: Drag["mode"]) {
    if (event.key === "Enter") {
      event.preventDefault();
      focusText();
      return;
    }
    if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key))
      return;
    event.preventDefault();
    event.stopPropagation();
    const step = event.shiftKey ? .01 : .001;
    const dx = event.key === "ArrowLeft" ? -step : event.key === "ArrowRight" ? step : 0;
    const dy = event.key === "ArrowUp" ? -step : event.key === "ArrowDown" ? step : 0;
    if (mode === "tail" && element.tail_target)
      change(element.id, { tail_target: { x: clamp(element.tail_target.x + dx, 0, 1), y: clamp(element.tail_target.y + dy, 0, 1) } });
    else if (mode === "resize")
      change(element.id, { tight_box: false, placement: { ...element.placement, width: clamp(elementRect(element).width + dx, .045, 1 - element.placement.x), height: clamp(elementRect(element).height + dy, .025, 1 - element.placement.y) } });
    else
      change(element.id, { placement: { ...element.placement, x: clamp(element.placement.x + dx, 0, 1 - elementRect(element).width), width: Math.min(element.placement.width, 1 - clamp(element.placement.x + dx, 0, 1 - elementRect(element).width)), y: clamp(element.placement.y + dy, 0, 1 - elementRect(element).height), height: Math.min(element.placement.height, 1 - clamp(element.placement.y + dy, 0, 1 - elementRect(element).height)) } });
  }
  return <div className="lettering-canvas-column">
    <Toolbar className="justify-between px-1" bottomRule={false}>
      <div className="flex gap-1">
        <Button variant="outline" size="xs" aria-label={t("Zoom out")} onClick={() => setZoom(z => Math.max(.5, z - .25))} disabled={zoom <= .5}>−</Button>
        <Button variant="outline" size="xs" onClick={() => setZoom(1)} title={t("Fit the full page")}>{t("Fit")} · {Math.round(zoom * 100)}%</Button>
        <Button variant="outline" size="xs" aria-label={t("Zoom in")} onClick={() => setZoom(z => Math.min(3, z + .25))} disabled={zoom >= 3}>+</Button>
      </div>
      <Button variant={panMode ? "secondary" : "outline"} size="xs" aria-pressed={panMode} onClick={() => setPanMode(p => !p)}>{panMode ? t("Pan enabled") : t("Pan")}</Button>
    </Toolbar>
    <div ref={viewport} className={`lettering-viewport ${panMode ? "is-panning" : ""}`} aria-label={t("Lettering page canvas")} onPointerDown={event => {
      if (!panMode || !viewport.current)
        return; pan.current = { x: event.clientX, y: event.clientY, left: viewport.current.scrollLeft, top: viewport.current.scrollTop }; event.currentTarget.setPointerCapture(event.pointerId);
    }} onPointerMove={event => {
      if (!pan.current || !viewport.current)
        return; viewport.current.scrollLeft = pan.current.left + pan.current.x - event.clientX; viewport.current.scrollTop = pan.current.top + pan.current.y - event.clientY;
    }} onPointerUp={() => { pan.current = null; }} onPointerCancel={() => { pan.current = null; }}>
      <div className="lettering-page-wrap" style={{ minWidth: width + 40, minHeight: width / state.canvas_aspect_ratio + 40 }}>
        <div ref={page} className="lettering-page" style={{ width, aspectRatio: state.canvas_aspect_ratio }} onClick={event => {
          if (event.target === event.currentTarget)
            select(null);
        }}>
          <img key={artUrl} src={artUrl} alt={t("Immutable base artwork")} className="lettering-base-art" draggable={false} onError={() => { setArtFailed(true); onArtReady(null); }} onLoad={() => { setArtFailed(false); onArtReady(artUrl); }} />
          <div className="lettering-svg" aria-hidden="true" dangerouslySetInnerHTML={{ __html: overlay }} />
          {guides && <div className="lettering-guides" aria-hidden="true">
            {(dragging && guides.dragFaces?.length ? guides.dragFaces : guides.faces).map((face, index) => <span key={index} className="lettering-guide-face" style={at(face)}><span>{face.label}</span></span>)}
            {guides.focus && <span className={`lettering-guide-focus is-${guides.focus.severity}`} style={at(guides.focus)} />}
          </div>}
          {state.elements.filter(e => !e.hidden).map((element, index) => {
            const rect = elementRect(element);
            return <button key={element.id} type="button" className={`lettering-hit ${selected === element.id ? "is-selected" : ""} ${element.resolved?.overflow ? "has-overflow" : ""}`} data-element-id={element.id} disabled={disabled || panMode} aria-pressed={selected === element.id} aria-label={`${t("Select lettering")} ${index + 1}: ${element.resolved?.text ?? ""}`} style={{ left: `${rect.x * 100}%`, top: `${rect.y * 100}%`, width: `${rect.width * 100}%`, height: `${rect.height * 100}%`, transform: `rotate(${element.rotation}deg) scale(${element.scale})`, zIndex: Math.max(1, element.z_index + 1001) }} onClick={event => { event.stopPropagation(); select(element.id); }} onDoubleClick={focusText} onPointerDown={event => down(event, element, "move")} onPointerMove={move} onPointerUp={end} onPointerCancel={abort} onLostPointerCapture={end} onKeyDown={event => nudge(event, element, "move")} />;
          })}
          {selectedElement && resizeHandle && !panMode && <>
              <button type="button" className="lettering-handle resize" aria-label={t("Resize selected lettering")} disabled={disabled} style={{ left: `${resizeHandle.x * 100}%`, top: `${resizeHandle.y * 100}%`, "--handle-rotation": `${selectedElement.rotation}deg` } as CSSProperties} onPointerDown={e => down(e, selectedElement, "resize")} onPointerMove={move} onPointerUp={end} onPointerCancel={abort} onLostPointerCapture={end} onKeyDown={e => nudge(e, selectedElement, "resize")}><span aria-hidden="true" /></button>
              {selectedElement.tail_target && <button type="button" className="lettering-handle tail" aria-label={t("Move balloon tail")} disabled={disabled} style={{ left: `${selectedElement.tail_target.x * 100}%`, top: `${selectedElement.tail_target.y * 100}%` }} onPointerDown={e => down(e, selectedElement, "tail")} onPointerMove={move} onPointerUp={end} onPointerCancel={abort} onLostPointerCapture={end} onKeyDown={e => nudge(e, selectedElement, "tail")}><span aria-hidden="true" /></button>}
          </>}
        </div>
      </div>
    </div>
    {artFailed && <p role="alert" className="lettering-error">{t("Base artwork could not load. Do not assess placement against this blank preview; reload the page.")}</p>}
    <p className="lettering-hint">{t("Select a box to move it. Drag its corner to resize. Double-click to edit words. Arrow keys nudge; Shift moves farther.")}</p>
  </div>;
}

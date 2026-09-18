import { useId, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { useI18n } from "../../i18n";
import type { PageAnnotationKind } from "../../api/pages";
import { Button } from "../ui/Button";
import { FieldLabel, TextField } from "../ui/Field";
import { Icon } from "../ui/Icon";
import type { IconName } from "../ui/Icon";
import { Surface } from "../ui/Surface";
import {
  FREEHAND_STEP, MAX_ANNOTATION_POINTS, newAnnotationId, roundPoint, simplifyStroke,
  type EditorAnnotation,
} from "./annotationGeometry";
import { annotationProblem, MAX_CORRECTION_MARKS, MAX_MARK_NOTE, moveAnnotation } from "./correctionValidation";

export type { EditorAnnotation };
type Point = { x: number; y: number };
type Tool = PageAnnotationKind | "select";
const PRIMARY_TOOLS: { id: PageAnnotationKind; label: string; icon: IconName }[] = [
  { id: "pin", label: "Pin", icon: "pin" },
  { id: "rectangle", label: "Area", icon: "rectangle" },
  { id: "highlight", label: "Highlight", icon: "highlight" },
];
const LABELS: Record<PageAnnotationKind, string> = {
  pin: "Pin", rectangle: "Area", highlight: "Highlight", freehand: "Outline", arrow: "Arrow",
};
const HINTS: Record<Tool, string> = {
  select: "Locations are optional. Select a tool, or select an existing location to adjust it.",
  pin: "Click once to place a pin. It uses the request's wording; no extra note is required.",
  rectangle: "Drag around the area you want to change.",
  highlight: "Drag over the part you want to highlight.",
  freehand: "Draw around the part you want to change.",
  arrow: "Drag from the label toward the part you want to change.",
};

interface AnnotationEditorProps {
  imageSrc: string;
  alt: string;
  value: EditorAnnotation[];
  onChange: (next: EditorAnnotation[]) => void;
  disabled?: boolean;
  /** Page-wide allowance: marks belonging to other requests still count. */
  maxMarks?: number;
  readOnly?: boolean;
}

/** Optional spatial context for one request, not a second request-writing task. */
export function AnnotationEditor({ imageSrc, alt, value, onChange, disabled: disabledProp, maxMarks = MAX_CORRECTION_MARKS, readOnly = false }: AnnotationEditorProps) {
  const disabled = disabledProp || readOnly;
  const { t } = useI18n();
  const id = useId();
  const [tool, setTool] = useState<Tool>("select");
  const [zoom, setZoom] = useState(1);
  const [showMarks, setShowMarks] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(value.at(-1)?.id ?? null);
  const [draft, setDraft] = useState<{ kind: PageAnnotationKind; points: Point[] } | null>(null);
  const [past, setPast] = useState<EditorAnnotation[][]>([]);
  const [future, setFuture] = useState<EditorAnnotation[][]>([]);
  const [notice, setNotice] = useState("");
  const [imageError, setImageError] = useState(false);
  const [aspectRatio, setAspectRatio] = useState(2 / 3);
  const moreRef = useRef<HTMLDetailsElement | null>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  // Pointer data lives in a ref: fast pointerup/cancel must never commit stale React state.
  const gesture = useRef<{ pointerId: number; kind: PageAnnotationKind; points: Point[] } | null>(null);
  const selected = value.find((mark) => mark.id === selectedId) ?? null;
  const full = value.length >= maxMarks;

  function commit(next: EditorAnnotation[]) {
    if (disabled) return;
    setPast((current) => [...current.slice(-49), value]);
    setFuture([]);
    onChange(next);
  }
  function undo() {
    if (disabled || past.length === 0) return;
    setFuture((current) => [value, ...current].slice(0, 50));
    setPast((current) => current.slice(0, -1));
    onChange(past[past.length - 1]!);
  }
  function redo() {
    if (disabled || future.length === 0) return;
    setPast((current) => [...current.slice(-49), value]);
    setFuture((current) => current.slice(1));
    onChange(future[0]!);
  }
  function cancelDrawing() {
    const current = gesture.current;
    gesture.current = null;
    setDraft(null);
    if (current && svgRef.current?.hasPointerCapture?.(current.pointerId)) {
      svgRef.current.releasePointerCapture(current.pointerId);
    }
  }
  function chooseTool(next: Tool) {
    cancelDrawing();
    if (moreRef.current) moreRef.current.open = false;
    setTool(next === tool ? "select" : next);
    setShowMarks(true);
    setNotice("");
  }
  function pointAt(event: PointerEvent): Point | null {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return null;
    return roundPoint({ x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height });
  }
  function pointerDown(event: PointerEvent<SVGSVGElement>) {
    if (disabled || imageError || full || tool === "select" || gesture.current
      || event.button > 0 || event.isPrimary === false) return;
    const point = pointAt(event);
    if (!point) return;
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    const points = tool === "pin" ? [point] : [point, point];
    gesture.current = { pointerId: event.pointerId, kind: tool, points };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDraft({ kind: tool, points });
  }
  function updateGesture(event: PointerEvent, ending = false) {
    const current = gesture.current;
    const point = pointAt(event);
    if (!current || current.pointerId !== event.pointerId || !point) return;
    if (current.kind === "pin") current.points = [point];
    else if (current.kind === "freehand") {
      const last = current.points[current.points.length - 1]!;
      if (ending || Math.hypot(point.x - last.x, point.y - last.y) >= FREEHAND_STEP) {
        const points = [...current.points, point];
        // Keep the latest endpoint, even on a very long gesture.
        current.points = points.length > MAX_ANNOTATION_POINTS * 4 ? simplifyStroke(points).points : points;
      }
    } else current.points = [current.points[0]!, point];
    setDraft({ kind: current.kind, points: [...current.points] });
  }
  function pointerUp(event: PointerEvent<SVGSVGElement>) {
    if (gesture.current?.pointerId !== event.pointerId) return;
    updateGesture(event, true);
    const current = gesture.current!;
    const points = current.kind === "freehand" ? simplifyStroke(current.points).points : current.points;
    const mark: EditorAnnotation = { id: newAnnotationId(current.kind), kind: current.kind, points };
    cancelDrawing();
    if (disabled || full || imageError) return;
    const problem = annotationProblem(mark);
    if (problem) { setNotice(t("Drag a little farther to select an area, or use Pin for a single spot.")); return; }
    commit([...value, mark]);
    setSelectedId(mark.id);
    setTool("select");
    setNotice(t("Location added. It uses this request's wording."));
  }
  function selectMark(markId: string) {
    cancelDrawing();
    setSelectedId(markId);
    setTool("select");
    setShowMarks(true);
  }
  function addCenterPin() {
    if (disabled || full || imageError) return;
    const mark: EditorAnnotation = { id: newAnnotationId("pin"), kind: "pin", points: [{ x: 0.5, y: 0.5 }] };
    commit([...value, mark]);
    selectMark(mark.id);
    if (moreRef.current) moreRef.current.open = false;
    svgRef.current?.focus({ preventScroll: true });
    setNotice(t("Pin added at the center. Use arrow keys to position it; Shift moves farther."));
  }
  function nudge(dx: number, dy: number) {
    if (!selected || disabled) return;
    commit(value.map((mark) => mark.id === selected.id ? moveAnnotation(mark, dx, dy) : mark));
  }
  function keyDown(event: KeyboardEvent) {
    if (disabled) return;
    if (event.key === "Escape") {
      if (gesture.current || tool !== "select") {
        event.preventDefault(); event.stopPropagation(); cancelDrawing(); setTool("select");
      }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault(); if (event.shiftKey) redo(); else undo(); return;
    }
    if (!selected) return;
    const step = event.shiftKey ? 0.05 : 0.01;
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step],
    };
    const move = moves[event.key];
    if (move) { event.preventDefault(); nudge(...move); }
    else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault(); commit(value.filter((mark) => mark.id !== selected.id));
    }
  }
  function changeNote(note: string) {
    if (!selected || disabled) return;
    const update = (marks: EditorAnnotation[]) => marks.map((mark) => mark.id === selected.id ? { ...mark, note } : mark);
    // Undo/redo belongs to geometry; it must not roll back a subsequently edited note.
    setPast((history) => history.map(update));
    setFuture((history) => history.map(update));
    onChange(update(value));
  }

  const height = 1000 / aspectRatio;
  return (
    <div className="space-y-3" aria-label={t("Optional page locations")}>
      {!readOnly && <div role="toolbar" aria-label={t("Annotation tools")} className="flex flex-wrap items-center gap-2">
        {PRIMARY_TOOLS.map((entry) => (
          <Button key={entry.id} size="xs" variant={tool === entry.id ? "primary" : "outline"}
            aria-pressed={tool === entry.id} disabled={disabled || full || imageError} onClick={() => chooseTool(entry.id)}>
            <Icon name={entry.icon} size={16} />{t(entry.label)}
          </Button>
        ))}
        <details ref={moreRef} className="relative ml-auto" onKeyDown={(event) => {
          if (event.key === "Escape" && moreRef.current?.open) {
            event.preventDefault(); event.stopPropagation(); moreRef.current.open = false;
            moreRef.current.querySelector("summary")?.focus();
          }
        }}>
          <summary className="min-h-11 cursor-pointer px-2 py-3 font-meta text-xs font-bold focus-visible:outline-2 focus-visible:outline-hero-red">
            {t("More")}
          </summary>
          <Surface border="soft" shadow="none" padding="md" className="absolute right-0 z-20 w-64 max-w-[80vw] space-y-3">
            <div className="flex flex-wrap gap-2">
              <Button size="xs" variant="outline" onClick={undo} disabled={disabled || past.length === 0}>{t("Undo mark")}</Button>
              <Button size="xs" variant="outline" onClick={redo} disabled={disabled || future.length === 0}>{t("Redo mark")}</Button>
              <Button size="xs" variant="outline" onClick={() => { cancelDrawing(); setTool("select"); setShowMarks(!showMarks); }} aria-pressed={showMarks}>
                {t(showMarks ? "Hide locations" : "Show locations")}
              </Button>
            </div>
            <FieldLabel htmlFor={`${id}-zoom`}>{t("View")}</FieldLabel>
            <select id={`${id}-zoom`} className="min-h-11 w-full bg-pulp-paper px-3 font-body text-sm" value={zoom}
              onChange={(event) => { cancelDrawing(); setZoom(Number(event.target.value)); }}>
              <option value={1}>{t("Fit page")}</option><option value={1.5}>150%</option><option value={2}>200%</option><option value={3}>300%</option>
            </select>
            <div className="flex flex-wrap gap-2">
              <Button size="xs" variant="outline" disabled={disabled || full || imageError} aria-pressed={tool === "freehand"} onClick={() => chooseTool("freehand")}>{t("Outline")}</Button>
              <Button size="xs" variant="outline" disabled={disabled || full || imageError} aria-pressed={tool === "arrow"} onClick={() => chooseTool("arrow")}>{t("Arrow")}</Button>
              <Button size="xs" variant="outline" disabled={disabled || full || imageError} onClick={addCenterPin}>{t("Place pin without drawing")}</Button>
            </div>
            <p className="font-body text-xs leading-5 text-ink-muted">{t("Select a location, then use arrow keys to move it or Delete to remove it. Escape cancels drawing.")}</p>
          </Surface>
        </details>
      </div>}
      <p id={`${id}-help`} role="status" className={readOnly ? "sr-only" : "min-h-10 font-body text-xs leading-5 text-ink-muted"}>
        {full ? t("All 24 page locations are in use. Remove a location to add another.") : notice || t(HINTS[tool])}
      </p>
      {imageError && <p role="alert" className="font-body text-sm text-hero-red">{t("The page image could not be loaded. You can still send a text-only request.")}</p>}
      <div className="max-h-[70dvh] overflow-auto bg-surface-container p-2">
        <div className="relative mx-auto w-fit max-w-full" style={zoom === 1 ? undefined : { width: `${zoom * 100}%`, maxWidth: "none" }}>
          <img src={imageSrc} alt={alt} draggable={false} className="block select-none"
            style={zoom === 1 ? { maxHeight: "65dvh", maxWidth: "100%", width: "auto", height: "auto" } : { width: "100%", height: "auto" }}
            onError={() => { cancelDrawing(); setImageError(true); }}
            onLoad={(event) => { setImageError(false); const img = event.currentTarget; if (img.naturalWidth && img.naturalHeight) setAspectRatio(img.naturalWidth / img.naturalHeight); }} />
          <svg ref={svgRef} viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none"
            className="absolute inset-0 h-full w-full focus-visible:outline-2 focus-visible:outline-hero-red"
            style={{ cursor: tool === "select" ? "default" : "crosshair", touchAction: tool === "select" ? "auto" : "none" }}
            role="group" aria-label={t("Page locations")} aria-describedby={`${id}-help`} tabIndex={disabled ? -1 : 0}
            onKeyDown={keyDown} onPointerDown={pointerDown} onPointerMove={(event) => updateGesture(event)} onPointerUp={pointerUp}
            onPointerCancel={cancelDrawing} onLostPointerCapture={cancelDrawing}>
            <defs>
              <marker id={`${id}-arrow`} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
                <path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke" />
              </marker>
            </defs>
            {showMarks && value.map((mark) => <MarkShape key={mark.id} mark={mark} height={height} selected={mark.id === selectedId}
              arrowId={`${id}-arrow`} onSelect={() => selectMark(mark.id)} />)}
            {showMarks && draft && <MarkShape mark={{ id: "draft", ...draft }} height={height} selected arrowId={`${id}-arrow`} />}
          </svg>
          {showMarks && value.map((mark, index) => {
            const first = mark.points[0];
            if (!first) return null;
            // HTML badges use CSS pixels, not stretched SVG coordinates. A 44px
            // invisible hit target surrounds the 26px square paper tag.
            return <button key={mark.id} type="button" aria-label={`${t("Select location")} ${index + 1}: ${t(LABELS[mark.kind])}`}
              aria-pressed={selectedId === mark.id} onClick={() => selectMark(mark.id)} onFocus={() => selectMark(mark.id)} onKeyDown={keyDown} disabled={disabled}
              className="absolute z-10 flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center focus-visible:outline-2 focus-visible:outline-hero-red"
              style={{ left: `clamp(22px, ${first.x * 100}%, calc(100% - 22px))`, top: `clamp(22px, ${first.y * 100}%, calc(100% - 22px))` }}>
              <span className={`flex h-[26px] w-[26px] items-center justify-center border-2 border-ink-black font-meta text-xs font-bold shadow-ink-sm outline outline-2 outline-bristol ${selectedId === mark.id ? "bg-hero-red text-bristol" : "bg-pulp-paper text-ink-black"}`}>{index + 1}</span>
            </button>;
          })}
        </div>
      </div>
      {!readOnly && value.length > 0 && <Surface border="soft" shadow="none" padding="md">
        <p className="font-meta text-xs font-bold text-ink-muted">{t("Locations for this request")} · {value.length}</p>
        <div role="group" aria-label={t("Saved locations")} className="mt-2 flex flex-wrap gap-2">
          {value.map((mark, index) => <Button key={mark.id} size="xs" variant={mark.id === selectedId ? "secondary" : "outline"}
            aria-pressed={mark.id === selectedId} onClick={() => selectMark(mark.id)}>
            {index + 1} · {t(LABELS[mark.kind])}
          </Button>)}
        </div>
        {selected && <div className="mt-3 space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="font-body text-xs leading-5 text-ink-muted">{t("Uses the request above. Extra detail is optional.")}</p>
            <Button size="xs" variant="outline" disabled={disabled} onClick={() => commit(value.filter((mark) => mark.id !== selected.id))}>{t("Remove location")}</Button>
          </div>
          <FieldLabel htmlFor={`mark-note-${selected.id}`}>{t("Extra detail (optional)")}</FieldLabel>
          <TextField id={`mark-note-${selected.id}`} value={selected.note ?? ""} disabled={disabled} maxLength={MAX_MARK_NOTE}
            placeholder={t("For example: only the coat, not the face.")} onChange={(event) => changeNote(event.target.value)} />
          {annotationProblem(selected) && <p role="alert" className="font-body text-xs text-hero-red">{t(annotationProblem(selected)!)}</p>}
        </div>}
      </Surface>}
    </div>
  );
}

function MarkShape({ mark, height, selected, arrowId, onSelect }: {
  mark: EditorAnnotation; height: number; selected: boolean; arrowId: string; onSelect?: () => void;
}) {
  const first = mark.points[0];
  if (!first) return null;
  const second = mark.points[1];
  const x = first.x * 1000;
  const y = first.y * height;
  const common = { vectorEffect: "non-scaling-stroke" as const, strokeWidth: 2.5, stroke: "currentColor" };
  let shape;
  if (mark.kind === "pin") shape = <path d={`M ${x - 8} ${y} h 16 M ${x} ${y - 8} v 16`} {...common} />;
  else if ((mark.kind === "rectangle" || mark.kind === "highlight") && second) {
    shape = <rect x={Math.min(first.x, second.x) * 1000} y={Math.min(first.y, second.y) * height}
      width={Math.abs(first.x - second.x) * 1000} height={Math.abs(first.y - second.y) * height} {...common}
      fill={mark.kind === "highlight" ? "var(--color-narrator-gold)" : "var(--color-pulp-paper)"} fillOpacity={mark.kind === "highlight" ? 0.3 : 0.08} />;
  } else if (mark.kind === "arrow" && second) {
    shape = <line x1={x} y1={y} x2={second.x * 1000} y2={second.y * height} {...common} markerEnd={`url(#${arrowId})`} />;
  } else if (mark.kind === "freehand") {
    shape = <polyline points={mark.points.map((p) => `${p.x * 1000},${p.y * height}`).join(" ")} {...common} />;
  } else return null;
  return <g fill="none" strokeLinejoin="round" strokeLinecap="round"
    className={selected ? "text-hero-red" : "text-ink-black"}
    style={{ filter: "drop-shadow(0 0 1px var(--color-bristol))", cursor: onSelect ? "pointer" : undefined }}
    onPointerDown={onSelect ? (event) => { event.stopPropagation(); onSelect(); } : undefined}>
    {shape}
  </g>;
}

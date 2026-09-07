import { useCallback, useRef, useState } from "react";
import { useI18n } from "../../i18n";
import type { PageAnnotationKind } from "../../api/pages";
import { Button } from "../ui/Button";
import { FieldLabel, TextField } from "../ui/Field";
import type { IconName } from "../ui/Icon";
import { IconButton } from "../ui/IconButton";
import { Surface } from "../ui/Surface";
import {
  FREEHAND_STEP,
  MAX_ANNOTATION_POINTS,
  MIN_POINTS,
  newAnnotationId,
  normalizeForSubmit,
  roundPoint,
  simplifyStroke,
  type EditorAnnotation,
} from "./annotationGeometry";

export type { EditorAnnotation };

type Tool = PageAnnotationKind | "select";

const TOOLS: { id: Tool; label: string; hint: string; icon: IconName }[] = [
  { id: "select", label: "Select", hint: "Click a mark to select it. Arrow keys nudge pins.", icon: "select" },
  { id: "pin", label: "Pin", hint: "Click the page to drop a numbered pin.", icon: "pin" },
  { id: "rectangle", label: "Rectangle", hint: "Drag a box around the area to fix.", icon: "rectangle" },
  { id: "highlight", label: "Highlight", hint: "Drag a box around lettering to re-set.", icon: "highlight" },
  { id: "freehand", label: "Freehand", hint: "Draw the outline of the problem area. Long strokes are thinned to 64 points.", icon: "freehand" },
  { id: "arrow", label: "Arrow", hint: "Drag from the problem toward its note.", icon: "arrow" },
];

interface AnnotationEditorProps {
  imageSrc: string;
  alt: string;
  value: EditorAnnotation[];
  onChange: (next: EditorAnnotation[]) => void;
  disabled?: boolean;
}

/**
 * Accessible page annotator. Marks are stored as normalized 0..1 geometry and
 * submitted verbatim with the correction; the numbered notes list is the full
 * keyboard/text path (add, rename, nudge, delete without a pointer).
 */
export function AnnotationEditor({ imageSrc, alt, value, onChange, disabled }: AnnotationEditorProps) {
  const { t } = useI18n();
  const [tool, setTool] = useState<Tool>("select");
  const [zoom, setZoom] = useState(1);
  const [showMarks, setShowMarks] = useState(true);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ x: number; y: number }[] | null>(null);
  const [past, setPast] = useState<EditorAnnotation[][]>([]);
  const [future, setFuture] = useState<EditorAnnotation[][]>([]);
  const [simplifiedNotice, setSimplifiedNotice] = useState(false);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const noteRefs = useRef(new Map<string, HTMLLIElement>());
  const drawingRef = useRef(false);

  // Derived, never synced: a selection that no longer exists selects nothing.
  const effectiveSelectedId = selectedId && value.some((mark) => mark.id === selectedId)
    ? selectedId
    : null;

  const commit = useCallback((next: EditorAnnotation[]) => {
    setPast((current) => [...current.slice(-49), value]);
    setFuture([]);
    onChange(next);
  }, [onChange, value]);

  function undo() {
    if (past.length === 0) return;
    const previous = past[past.length - 1]!;
    setFuture((current) => [value, ...current].slice(0, 50));
    setPast((current) => current.slice(0, -1));
    onChange(previous);
  }

  function redo() {
    if (future.length === 0) return;
    const [next, ...rest] = future;
    setPast((current) => [...current, value]);
    setFuture(rest);
    onChange(next!);
  }

  function toNormalized(event: React.PointerEvent): { x: number; y: number } {
    const rect = svgRef.current!.getBoundingClientRect();
    return {
      x: (event.clientX - rect.left) / rect.width,
      y: (event.clientY - rect.top) / rect.height,
    };
  }

  function handlePointerDown(event: React.PointerEvent) {
    if (disabled || tool === "select" || !svgRef.current) return;
    (event.target as Element).setPointerCapture?.(event.pointerId);
    drawingRef.current = true;
    const point = toNormalized(event);
    setDraft(tool === "pin" ? [point] : [point, point]);
  }

  function handlePointerMove(event: React.PointerEvent) {
    if (!drawingRef.current || !draft) return;
    const point = toNormalized(event);
    if (tool === "freehand") {
      setDraft((current) => {
        if (!current) return current;
        const last = current[current.length - 1]!;
        const moved = Math.hypot(point.x - last.x, point.y - last.y);
        if (moved < FREEHAND_STEP) return current;
        return current.length >= MAX_ANNOTATION_POINTS * 4
          ? current
          : [...current, point];
      });
    } else if (tool === "pin") {
      setDraft([point]);
    } else {
      setDraft((current) => (current ? [current[0]!, point] : current));
    }
  }

  function handlePointerUp() {
    if (!drawingRef.current) return;
    drawingRef.current = false;
    if (draft && tool !== "select") {
      const kind = tool as PageAnnotationKind;
      const rounded = (kind === "pin" ? draft.slice(0, 1) : draft).map(roundPoint);
      const { points, simplified } = kind === "freehand"
        ? simplifyStroke(rounded)
        : { points: rounded, simplified: false };
      if (points.length >= MIN_POINTS[kind]) {
        const mark: EditorAnnotation = { id: newAnnotationId(kind), kind, points };
        commit([...value, mark]);
        setSelectedId(mark.id);
        setSimplifiedNotice(simplified);
      }
    }
    setDraft(null);
  }

  function nudgeSelected(dx: number, dy: number) {
    if (!effectiveSelectedId) return;
    commit(value.map((mark) => {
      if (mark.id !== effectiveSelectedId) return mark;
      return { ...mark, points: mark.points.map((point) => roundPoint({ x: point.x + dx, y: point.y + dy })) };
    }));
  }

  function handleCanvasKeyDown(event: React.KeyboardEvent) {
    if (disabled) return;
    const step = event.shiftKey ? 0.05 : 0.01;
    if (event.key === "ArrowLeft") { event.preventDefault(); nudgeSelected(-step, 0); }
    else if (event.key === "ArrowRight") { event.preventDefault(); nudgeSelected(step, 0); }
    else if (event.key === "ArrowUp") { event.preventDefault(); nudgeSelected(0, -step); }
    else if (event.key === "ArrowDown") { event.preventDefault(); nudgeSelected(0, step); }
    else if ((event.key === "Delete" || event.key === "Backspace") && effectiveSelectedId) {
      event.preventDefault();
      commit(value.filter((mark) => mark.id !== effectiveSelectedId));
    }
  }

  function addTextPin() {
    if (disabled) return;
    const mark: EditorAnnotation = {
      id: newAnnotationId("pin"),
      kind: "pin",
      points: [{ x: 0.5, y: 0.5 }],
      note: "",
    };
    commit([...value, mark]);
    setSelectedId(mark.id);
  }

  function selectMark(id: string) {
    setSelectedId(id);
    noteRefs.current.get(id)?.scrollIntoView({ block: "nearest" });
  }

  const activeTool = TOOLS.find((entry) => entry.id === tool)!;
  const submitted = normalizeForSubmit(value);
  const dirtyGeometry = submitted.length !== value.length;

  return (
    <div className="space-y-3">
      <div
        role="toolbar"
        aria-label={t("Annotation tools")}
        className="flex flex-wrap items-center gap-x-3 gap-y-1.5"
      >
        <div role="group" aria-label={t("Draw tools")} className="flex items-center gap-1">
          {TOOLS.map((entry) => (
            <IconButton
              key={entry.id}
              size="sm"
              icon={entry.icon}
              label={t(entry.label.toUpperCase())}
              title={`${t(entry.label.toUpperCase())} — ${t(entry.hint)}`}
              aria-pressed={tool === entry.id}
              variant={tool === entry.id ? "primary" : "outline"}
              onClick={() => setTool(entry.id)}
              disabled={disabled}
            />
          ))}
        </div>
        <div role="group" aria-label={t("Mark history")} className="flex items-center gap-1">
          <IconButton size="sm" icon="undo" label={t("Undo mark")} onClick={undo} disabled={disabled || past.length === 0} />
          <IconButton size="sm" icon="redo" label={t("Redo mark")} onClick={redo} disabled={disabled || future.length === 0} />
          <IconButton
            size="sm"
            icon="eye"
            label={showMarks ? t("HIDE MARKS") : t("SHOW MARKS")}
            aria-pressed={showMarks}
            onClick={() => setShowMarks((current) => !current)}
          />
        </div>
        <div role="group" aria-label={t("Zoom")} className="flex items-center gap-1">
          <IconButton size="sm" icon="zoom-out" label={t("Zoom out")} onClick={() => setZoom((z) => Math.max(0.5, Math.round((z - 0.25) * 100) / 100))} disabled={disabled || zoom <= 0.5} />
          <span className="min-w-11 text-center font-meta text-xs font-bold" role="status" aria-label={t("Zoom level")}>{Math.round(zoom * 100)}%</span>
          <IconButton size="sm" icon="zoom-in" label={t("Zoom in")} onClick={() => setZoom((z) => Math.min(4, Math.round((z + 0.25) * 100) / 100))} disabled={disabled || zoom >= 4} />
          <IconButton size="sm" icon="reset" label={t("RESET ZOOM")} onClick={() => setZoom(1)} disabled={disabled || zoom === 1} />
        </div>
      </div>
      <p role="status" className="font-body text-xs leading-5 text-ink-muted">
        <span className="font-meta font-bold">{t(activeTool.label.toUpperCase())}</span>
        {dirtyGeometry && ` · ${t("Incomplete marks are not submitted.")}`}
        {simplifiedNotice && ` · ${t("The last long stroke was thinned to 64 points; its shape and note are preserved.")}`}
      </p>
      <div className="max-h-[70vh] overflow-auto border-[2px] border-ink-black bg-bristol">
        <div style={{ width: `${zoom * 100}%`, minWidth: "100%" }} className="relative">
          <img src={imageSrc} alt={alt} className="block w-full select-none" draggable={false} />
          <svg
            ref={svgRef}
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="absolute inset-0 h-full w-full touch-none"
            style={{ cursor: tool === "select" ? "default" : "crosshair" }}
            role="application"
            aria-label={t("Page marks. Use arrow keys to move the selected mark, Delete to remove it.")}
            tabIndex={disabled ? -1 : 0}
            onKeyDown={handleCanvasKeyDown}
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
          >
            {showMarks && value.map((mark, index) => (
              <MarkShape
                key={mark.id}
                mark={mark}
                number={index + 1}
                selected={mark.id === effectiveSelectedId}
                onSelect={() => selectMark(mark.id)}
              />
            ))}
            {showMarks && draft && tool !== "select" && (
              <MarkShape
                mark={{ id: "draft", kind: tool as PageAnnotationKind, points: draft }}
                number={value.length + 1}
                selected={false}
                onSelect={() => {}}
              />
            )}
          </svg>
        </div>
      </div>

      {value.length === 0 ? (
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-body text-xs text-ink-muted">
            {t("No marks yet. Every mark needs a note before submission.")}
          </p>
          <Button size="xs" variant="outline" onClick={addTextPin} disabled={disabled}>
            {t("ADD NOTE WITHOUT DRAWING")}
          </Button>
        </div>
      ) : (
      <Surface tone="bristol" border="soft" shadow="none" padding="md">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h4 className="font-meta text-xs font-bold text-ink-muted">
            {t("NUMBERED NOTES")} · {value.length}
          </h4>
          <Button size="xs" variant="outline" onClick={addTextPin} disabled={disabled}>
            {t("ADD NOTE WITHOUT DRAWING")}
          </Button>
        </div>
          <ol className="mt-3 space-y-3">
            {value.map((mark, index) => (
              <li
                key={mark.id}
                ref={(node) => {
                  if (node) noteRefs.current.set(mark.id, node);
                  else noteRefs.current.delete(mark.id);
                }}
                className={`border p-2 ${mark.id === effectiveSelectedId ? "border-hero-red" : "border-ink-black/20"}`}
              >
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => selectMark(mark.id)}
                    aria-label={`${t("Select mark")} ${index + 1}`}
                    className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ink-black font-meta text-[0.7rem] font-bold text-bristol focus-visible:outline focus-visible:outline-2 focus-visible:outline-hero-red"
                  >
                    {index + 1}
                  </button>
                  <span className="font-meta text-[0.65rem] font-bold uppercase text-ink-muted">{mark.kind}</span>
                  <span className="font-mono text-[0.65rem] text-ink-muted">
                    {mark.points.map((p) => `${p.x.toFixed(2)},${p.y.toFixed(2)}`).join(" ")}
                  </span>
                  <span className="ml-auto flex gap-1.5">
                    <IconButton
                      size="sm"
                      icon="arrow-left"
                      label={`${t("Move mark")} ${index + 1} ${t("left")}`}
                      onClick={() => nudgeSelected(-0.01, 0)}
                      disabled={disabled || mark.id !== effectiveSelectedId}
                    />
                    <IconButton
                      size="sm"
                      icon="arrow-right"
                      label={`${t("Move mark")} ${index + 1} ${t("right")}`}
                      onClick={() => nudgeSelected(0.01, 0)}
                      disabled={disabled || mark.id !== effectiveSelectedId}
                    />
                    <IconButton
                      size="sm"
                      icon="trash"
                      label={`${t("Delete mark")} ${index + 1}`}
                      onClick={() => commit(value.filter((candidate) => candidate.id !== mark.id))}
                      disabled={disabled}
                    />
                  </span>
                </div>
                <div className="mt-2">
                  <FieldLabel htmlFor={`mark-note-${mark.id}`} className="sr-only">
                    {`${t("Note for mark")} ${index + 1}`}
                  </FieldLabel>
                  <TextField
                    id={`mark-note-${mark.id}`}
                    value={mark.note ?? ""}
                    disabled={disabled}
                    placeholder={t("What should change at this mark?")}
                    onChange={(event) => {
                      const note = event.target.value;
                      onChange(value.map((candidate) => candidate.id === mark.id ? { ...candidate, note } : candidate));
                    }}
                    onFocus={() => setSelectedId(mark.id)}
                  />
                </div>
              </li>
            ))}
          </ol>
      </Surface>
      )}
    </div>
  );
}

function MarkShape({ mark, number, selected, onSelect }: {
  mark: EditorAnnotation;
  number: number;
  selected: boolean;
  onSelect: () => void;
}) {
  const stroke = selected ? "#c1272d" : "#1a1a1a";
  const common = {
    stroke,
    strokeWidth: 0.7,
    vectorEffect: "non-scaling-stroke" as const,
    style: { cursor: "pointer" } as const,
    onClick: (event: React.MouseEvent) => { event.stopPropagation(); onSelect(); },
  };
  const numberBadge = (x: number, y: number) => (
    <g pointerEvents="none">
      <circle cx={x} cy={y} r={2.2} fill={selected ? "#c1272d" : "#1a1a1a"} />
      <text x={x} y={y + 1.4} textAnchor="middle" fontSize={2.6} fill="#fff" fontWeight="bold">{number}</text>
    </g>
  );
  const [first, second] = [mark.points[0], mark.points[1]];
  if (mark.kind === "pin" && first) {
    return (
      <g>
        <circle cx={first.x * 100} cy={first.y * 100} r={1.6} fill="none" {...common} />
        {numberBadge(first.x * 100, first.y * 100)}
      </g>
    );
  }
  if ((mark.kind === "rectangle" || mark.kind === "highlight") && first && second) {
    const x = Math.min(first.x, second.x) * 100;
    const y = Math.min(first.y, second.y) * 100;
    return (
      <g>
        <rect
          x={x}
          y={y}
          width={Math.abs(second.x - first.x) * 100}
          height={Math.abs(second.y - first.y) * 100}
          fill={mark.kind === "highlight" ? "rgba(193,39,45,0.15)" : "none"}
          strokeDasharray={mark.kind === "highlight" ? undefined : "2 1"}
          {...common}
        />
        {numberBadge(x, y)}
      </g>
    );
  }
  if (mark.kind === "arrow" && first && second) {
    return (
      <g>
        <line x1={first.x * 100} y1={first.y * 100} x2={second.x * 100} y2={second.y * 100} {...common} />
        {numberBadge(first.x * 100, first.y * 100)}
      </g>
    );
  }
  if (mark.kind === "freehand" && mark.points.length > 1) {
    return (
      <g>
        <polyline
          points={mark.points.map((p) => `${p.x * 100},${p.y * 100}`).join(" ")}
          fill="none"
          {...common}
        />
        {numberBadge(mark.points[0]!.x * 100, mark.points[0]!.y * 100)}
      </g>
    );
  }
  return null;
}

import { useId, useRef, useState } from "react";
import type { KeyboardEvent, PointerEvent } from "react";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { FieldLabel, TextField } from "../ui/Field";
import { newAnnotationId, roundPoint, type EditorAnnotation } from "./annotationGeometry";
import { MAX_MARK_NOTE, moveAnnotation } from "./correctionValidation";

export type { EditorAnnotation };
type Point = { x: number; y: number };

/** The marks belonging to one change, shown with that change's number. */
export interface MarkGroup {
  id: string;
  number: number;
  marks: EditorAnnotation[];
}

/** Shorter drags than this place a pin instead of an area. */
const AREA_MIN = 0.015;

interface PageMarkerProps {
  imageSrc: string;
  alt: string;
  groups: MarkGroup[];
  /** The change new marks belong to; without one the page only shows marks. */
  activeId: string | null;
  onChange: (groupId: string, marks: EditorAnnotation[]) => void;
  onActivate: (groupId: string | null) => void;
  /** Marks still allowed across the whole revision. */
  remaining: number;
  disabled?: boolean;
  onLoaded?: () => void;
}

/**
 * The page itself is the marking surface: click for a pin, drag for an area.
 * Every mark carries its change's number; there are no tools to choose.
 */
export function PageMarker({ imageSrc, alt, groups, activeId, onChange, onActivate, remaining, disabled, onLoaded }: PageMarkerProps) {
  const { t } = useI18n();
  const id = useId();
  const svgRef = useRef<SVGSVGElement | null>(null);
  // Pointer data lives in a ref: fast pointerup/cancel must never commit stale React state.
  const gesture = useRef<{ pointerId: number; points: [Point, Point] } | null>(null);
  const [draft, setDraft] = useState<[Point, Point] | null>(null);
  const [selected, setSelected] = useState<{ groupId: string; markId: string } | null>(null);
  const [undoStack, setUndoStack] = useState<{ groupId: string; marks: EditorAnnotation[] }[]>([]);
  const [imageError, setImageError] = useState(false);
  const [ratio, setRatio] = useState(2 / 3);
  const active = groups.find((group) => group.id === activeId) ?? null;
  const canMark = !!active && !disabled && !imageError && remaining > 0;
  const selectedGroup = selected ? groups.find((group) => group.id === selected.groupId) : undefined;
  const selectedMark = selectedGroup?.marks.find((mark) => mark.id === selected?.markId) ?? null;

  function commit(groupId: string, marks: EditorAnnotation[]) {
    const before = groups.find((group) => group.id === groupId)?.marks ?? [];
    setUndoStack((stack) => [...stack.slice(-49), { groupId, marks: before }]);
    onChange(groupId, marks);
  }
  function undo() {
    const last = undoStack.at(-1);
    if (!last || disabled) return;
    setUndoStack((stack) => stack.slice(0, -1));
    // Only a change still in the revision can be restored.
    if (groups.some((group) => group.id === last.groupId)) onChange(last.groupId, last.marks);
    setSelected(null);
  }
  function add(mark: EditorAnnotation) {
    if (!active) return;
    commit(active.id, [...active.marks, mark]);
    setSelected({ groupId: active.id, markId: mark.id });
  }
  function remove(groupId: string, markId: string) {
    const group = groups.find((candidate) => candidate.id === groupId);
    if (!group || disabled) return;
    commit(groupId, group.marks.filter((mark) => mark.id !== markId));
    setSelected(null);
  }
  function cancel() {
    const current = gesture.current;
    gesture.current = null;
    setDraft(null);
    if (current && svgRef.current?.hasPointerCapture?.(current.pointerId)) svgRef.current.releasePointerCapture(current.pointerId);
  }
  function pointAt(event: PointerEvent): Point | null {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || rect.width <= 0 || rect.height <= 0) return null;
    return roundPoint({ x: (event.clientX - rect.left) / rect.width, y: (event.clientY - rect.top) / rect.height });
  }
  function pointerDown(event: PointerEvent<SVGSVGElement>) {
    if (!canMark || gesture.current || event.button > 0 || event.isPrimary === false) return;
    const point = pointAt(event);
    if (!point) return;
    event.preventDefault();
    event.currentTarget.focus({ preventScroll: true });
    gesture.current = { pointerId: event.pointerId, points: [point, point] };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    setDraft([point, point]);
  }
  function pointerMove(event: PointerEvent) {
    const current = gesture.current;
    const point = pointAt(event);
    if (!current || current.pointerId !== event.pointerId || !point) return;
    current.points = [current.points[0], point];
    setDraft([...current.points]);
  }
  function pointerUp(event: PointerEvent<SVGSVGElement>) {
    if (gesture.current?.pointerId !== event.pointerId) return;
    pointerMove(event);
    const [start, end] = gesture.current.points;
    cancel();
    if (!canMark) return;
    const isArea = Math.abs(end.x - start.x) >= AREA_MIN && Math.abs(end.y - start.y) >= AREA_MIN;
    add(isArea
      ? { id: newAnnotationId("rectangle"), kind: "rectangle", points: [start, end] }
      : { id: newAnnotationId("pin"), kind: "pin", points: [start] });
  }
  function keyDown(event: KeyboardEvent) {
    if (disabled) return;
    if (event.key === "Escape") {
      if (gesture.current) { event.preventDefault(); event.stopPropagation(); cancel(); }
      else if (selected) { event.preventDefault(); event.stopPropagation(); setSelected(null); }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
      event.preventDefault(); undo(); return;
    }
    if (!selectedMark || !selected) {
      // Keyboard placement: a centered pin, then arrow keys move it.
      if ((event.key === "Enter" || event.key === " ") && event.currentTarget === svgRef.current && canMark) {
        event.preventDefault();
        add({ id: newAnnotationId("pin"), kind: "pin", points: [{ x: 0.5, y: 0.5 }] });
      }
      return;
    }
    const step = event.shiftKey ? 0.05 : 0.01;
    const moves: Record<string, [number, number]> = {
      ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step],
    };
    const move = moves[event.key];
    if (move) {
      event.preventDefault();
      commit(selected.groupId, selectedGroup!.marks.map((mark) => mark.id === selectedMark.id ? moveAnnotation(mark, ...move) : mark));
    } else if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      remove(selected.groupId, selectedMark.id);
    }
  }
  function select(groupId: string, markId: string) {
    cancel();
    setSelected({ groupId, markId });
    if (groupId !== activeId) onActivate(groupId);
  }
  function changeNote(note: string) {
    if (!selected || !selectedGroup || disabled) return;
    // Notes are wording, not geometry: undo must never roll an edited note back.
    const update = (marks: EditorAnnotation[]) => marks.map((mark) => mark.id === selected.markId ? { ...mark, note } : mark);
    setUndoStack((stack) => stack.map((entry) => entry.groupId === selected.groupId ? { ...entry, marks: update(entry.marks) } : entry));
    onChange(selected.groupId, update(selectedGroup.marks));
  }

  const height = 1000 / ratio;
  return (
    // Clipped with room for shadows and focus rings: a hover shift must never overflow the scrolling
    // column, or a flickering scrollbar would resize the page under the pointer.
    <div className="flex h-full w-full flex-col gap-3 overflow-hidden p-1.5">
      <p id={`${id}-help`} className="sr-only">
        {t("Click the page to place a pin, or drag to mark an area. Enter places a pin you can move with the arrow keys; Delete removes it.")}
      </p>
      {imageError && <p role="alert" className="font-body text-sm text-hero-red">{t("The page image could not be loaded.")}</p>}
      <div className="flex min-h-0 flex-1 items-center justify-center [container-type:size]">
        <div className="relative" style={{ width: `min(100cqw, calc(100cqh * ${ratio}))`, aspectRatio: `${ratio}` }}>
          <img src={imageSrc} alt={alt} draggable={false} className="absolute inset-0 block h-full w-full select-none"
            onError={() => { cancel(); setImageError(true); }}
            onLoad={(event) => {
              setImageError(false);
              const img = event.currentTarget;
              if (img.naturalWidth && img.naturalHeight) setRatio(img.naturalWidth / img.naturalHeight);
              onLoaded?.();
            }} />
          <svg ref={svgRef} viewBox={`0 0 1000 ${height}`} preserveAspectRatio="none"
            className="absolute inset-0 h-full w-full focus-visible:outline-2 focus-visible:outline-hero-red"
            style={{ cursor: canMark ? "crosshair" : "default", touchAction: canMark ? "none" : "auto" }}
            role="group" aria-label={t("Page marks")} aria-describedby={`${id}-help`} tabIndex={disabled ? -1 : 0}
            onKeyDown={keyDown} onPointerDown={pointerDown} onPointerMove={pointerMove} onPointerUp={pointerUp}
            onPointerCancel={cancel} onLostPointerCapture={cancel}>
            {groups.flatMap((group) => group.marks.map((mark) => (
              <MarkShape key={mark.id} mark={mark} height={height}
                tone={selected?.markId === mark.id ? "selected" : group.id === activeId || !activeId ? "active" : "muted"}
                onSelect={disabled ? undefined : () => select(group.id, mark.id)} />
            )))}
            {draft && <MarkShape mark={{ id: "draft", kind: "rectangle", points: draft }} height={height} tone="selected" />}
          </svg>
          {groups.flatMap((group) => group.marks.map((mark) => {
            const xs = mark.points.map((point) => point.x);
            const ys = mark.points.map((point) => point.y);
            if (xs.length === 0) return null;
            const isSelected = selected?.markId === mark.id;
            const muted = !!activeId && group.id !== activeId && !isSelected;
            // A 44px hit target around a 24px numbered tag at the mark's top-left.
            return <button key={mark.id} type="button" disabled={disabled}
              aria-label={t("Mark for change {number}", { number: group.number })} aria-pressed={isSelected}
              onClick={() => select(group.id, mark.id)} onKeyDown={keyDown}
              className="absolute z-10 flex size-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center focus-visible:outline-2 focus-visible:outline-hero-red"
              style={{ left: `clamp(22px, ${Math.min(...xs) * 100}%, calc(100% - 22px))`, top: `clamp(22px, ${Math.min(...ys) * 100}%, calc(100% - 22px))` }}>
              <span className={`flex size-6 items-center justify-center rounded-full border-2 border-ink-black font-meta text-xs font-bold shadow-ink-sm ${isSelected ? "bg-hero-red text-bristol" : "bg-pulp-paper text-ink-black"} ${muted ? "opacity-50" : ""}`}>
                {group.number}
              </span>
            </button>;
          }))}
        </div>
      </div>
      {selected && selectedMark && (
        <div className="flex flex-wrap items-end gap-2">
          <div className="min-w-48 flex-1">
            <FieldLabel htmlFor={`mark-note-${selectedMark.id}`}>{t("Note for mark {number} (optional)", { number: selectedGroup!.number })}</FieldLabel>
            <TextField id={`mark-note-${selectedMark.id}`} value={selectedMark.note ?? ""} disabled={disabled} maxLength={MAX_MARK_NOTE}
              placeholder={t("For example: only the coat, not the face.")} onChange={(event) => changeNote(event.target.value)} />
          </div>
          <Button size="xs" variant="outline" disabled={disabled} onClick={() => remove(selected.groupId, selectedMark.id)}>
            {t("REMOVE MARK")}
          </Button>
        </div>
      )}
    </div>
  );
}

function MarkShape({ mark, height, tone, onSelect }: {
  mark: EditorAnnotation; height: number; tone: "active" | "muted" | "selected"; onSelect?: () => void;
}) {
  const first = mark.points[0];
  if (!first) return null;
  const second = mark.points[1];
  const x = first.x * 1000;
  const y = first.y * height;
  const common = { vectorEffect: "non-scaling-stroke" as const, strokeWidth: 2.5, stroke: "currentColor" };
  let shape;
  if (mark.kind === "pin") shape = <circle cx={x} cy={y} r={7} {...common} fill="var(--color-hero-red)" fillOpacity={0.35} />;
  else if ((mark.kind === "rectangle" || mark.kind === "highlight") && second) {
    shape = <rect x={Math.min(first.x, second.x) * 1000} y={Math.min(first.y, second.y) * height}
      width={Math.abs(first.x - second.x) * 1000} height={Math.abs(first.y - second.y) * height} {...common}
      strokeDasharray="6 4" fill="var(--color-hero-red)" fillOpacity={0.08} />;
  } else if (mark.kind === "arrow" && second) {
    shape = <line x1={x} y1={y} x2={second.x * 1000} y2={second.y * height} {...common} />;
  } else if (mark.kind === "freehand") {
    shape = <polyline points={mark.points.map((p) => `${p.x * 1000},${p.y * height}`).join(" ")} {...common} />;
  } else return null;
  return <g fill="none" strokeLinejoin="round" strokeLinecap="round"
    className={tone === "selected" ? "text-hero-red" : "text-ink-black"}
    opacity={tone === "muted" ? 0.4 : 1}
    style={{ filter: "drop-shadow(0 0 1px var(--color-bristol))", cursor: onSelect ? "pointer" : undefined }}
    onPointerDown={onSelect ? (event) => { event.stopPropagation(); onSelect(); } : undefined}>
    {shape}
  </g>;
}

import { useRef, useState } from "react";
import type { LayoutRegion, PromptLayout } from "../types/api";
import { CollapsibleSection } from "./ui/CollapsibleSection";
import { EditableText } from "./ui/EditableText";
import { cn } from "../lib/cn";

// Region overlay palette — indexes wrap. Kept to ink-adjacent hues so boxes
// read as annotation marks over the artwork, not UI chrome.
const REGION_COLORS = [
  "#1d4ed8", // blue
  "#b45309", // amber
  "#15803d", // green
  "#b91c1c", // red
  "#7e22ce", // purple
  "#0e7490", // cyan
];

const MIN_SPAN = 0.02;

type DragMode =
  | { kind: "move"; index: number; startX: number; startY: number; bbox: LayoutRegion["bbox"] }
  | { kind: "resize"; index: number; corner: "nw" | "ne" | "sw" | "se"; bbox: LayoutRegion["bbox"] };

const clamp01 = (v: number) => Math.min(1, Math.max(0, v));

function regionColor(index: number) {
  return REGION_COLORS[index % REGION_COLORS.length];
}

/**
 * Interactive editor for the flat layout-aware region map (Reve v2).
 *
 * The canvas shows the panel image (when drawn) with normalized [0,1] bounding
 * boxes overlaid; boxes drag to move and resize from the corners. The list
 * below edits each region's label and prompt. All edits flow up through
 * onChange as a whole PromptLayout so the caller's prompt draft stays the
 * single source of truth.
 */
export function LayoutRegionEditor({
  layout,
  imageUrl,
  aspectRatio,
  onChange,
}: {
  layout: PromptLayout;
  imageUrl?: string | null;
  aspectRatio: number;
  onChange: (layout: PromptLayout) => void;
}) {
  const canvasRef = useRef<HTMLDivElement>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [drag, setDrag] = useState<DragMode | null>(null);

  const regions = layout.regions ?? [];

  const patchRegion = (index: number, patch: Partial<LayoutRegion>) => {
    onChange({
      ...layout,
      regions: regions.map((r, i) => (i === index ? { ...r, ...patch } : r)),
    });
  };

  const removeRegion = (index: number) => {
    setSelected(null);
    onChange({ ...layout, regions: regions.filter((_, i) => i !== index) });
  };

  const addRegion = () => {
    const label = nextLabel(regions);
    onChange({
      ...layout,
      regions: [
        ...regions,
        { label, prompt: "", bbox: { x0: 0.3, y0: 0.3, x1: 0.7, y1: 0.7 } },
      ],
    });
    setSelected(regions.length);
  };

  // Pointer position in normalized canvas coordinates.
  const toNorm = (e: { clientX: number; clientY: number }) => {
    const rect = canvasRef.current?.getBoundingClientRect();
    if (!rect || rect.width === 0 || rect.height === 0) return { x: 0, y: 0 };
    return {
      x: clamp01((e.clientX - rect.left) / rect.width),
      y: clamp01((e.clientY - rect.top) / rect.height),
    };
  };

  const beginMove = (index: number) => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    const { x, y } = toNorm(e);
    setSelected(index);
    setDrag({ kind: "move", index, startX: x, startY: y, bbox: { ...regions[index].bbox } });
  };

  const beginResize = (index: number, corner: "nw" | "ne" | "sw" | "se") => (e: React.PointerEvent) => {
    e.preventDefault();
    e.stopPropagation();
    (e.target as Element).setPointerCapture(e.pointerId);
    setSelected(index);
    setDrag({ kind: "resize", index, corner, bbox: { ...regions[index].bbox } });
  };

  const onPointerMove = (e: React.PointerEvent) => {
    if (!drag) return;
    const { x, y } = toNorm(e);
    if (drag.kind === "move") {
      const w = drag.bbox.x1 - drag.bbox.x0;
      const h = drag.bbox.y1 - drag.bbox.y0;
      const x0 = Math.min(Math.max(drag.bbox.x0 + (x - drag.startX), 0), 1 - w);
      const y0 = Math.min(Math.max(drag.bbox.y0 + (y - drag.startY), 0), 1 - h);
      patchRegion(drag.index, {
        bbox: {
          x0: round4(x0),
          y0: round4(y0),
          x1: round4(x0 + w),
          y1: round4(y0 + h),
        },
      });
    } else {
      const b = { ...regions[drag.index].bbox };
      if (drag.corner.includes("w")) b.x0 = Math.min(x, b.x1 - MIN_SPAN);
      if (drag.corner.includes("e")) b.x1 = Math.max(x, b.x0 + MIN_SPAN);
      if (drag.corner.includes("n")) b.y0 = Math.min(y, b.y1 - MIN_SPAN);
      if (drag.corner.includes("s")) b.y1 = Math.max(y, b.y0 + MIN_SPAN);
      patchRegion(drag.index, {
        bbox: { x0: round4(b.x0), y0: round4(b.y0), x1: round4(b.x1), y1: round4(b.y1) },
      });
    }
  };

  const endDrag = () => setDrag(null);

  return (
    <div className="flex flex-col gap-3">
      <div
        ref={canvasRef}
        className="relative w-full select-none overflow-hidden border-[2px] border-panel-line bg-ink-black/5"
        style={{ aspectRatio: `${aspectRatio}`, touchAction: "none" }}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onPointerDown={() => setSelected(null)}
      >
        {imageUrl && (
          <img
            src={imageUrl}
            alt="Panel layout backdrop"
            className="pointer-events-none absolute inset-0 h-full w-full object-fill opacity-60"
            draggable={false}
          />
        )}
        {regions.map((region, index) => {
          const { x0, y0, x1, y1 } = region.bbox;
          const isSelected = selected === index;
          const color = regionColor(index);
          return (
            <div
              key={index}
              className="absolute cursor-move"
              style={{
                left: `${x0 * 100}%`,
                top: `${y0 * 100}%`,
                width: `${(x1 - x0) * 100}%`,
                height: `${(y1 - y0) * 100}%`,
                border: `2px ${isSelected ? "solid" : "dashed"} ${color}`,
                background: isSelected ? `${color}1f` : "transparent",
                zIndex: isSelected ? 20 : 10,
              }}
              onPointerDown={beginMove(index)}
            >
              <span
                className="absolute -top-px left-0 max-w-full truncate px-1 font-meta text-[0.5rem] tracking-[0.12em] text-white"
                style={{ background: color }}
              >
                {region.label.toUpperCase()}
                {region.reference_key ? " ◈" : ""}
              </span>
              {isSelected &&
                (["nw", "ne", "sw", "se"] as const).map((corner) => (
                  <span
                    key={corner}
                    onPointerDown={beginResize(index, corner)}
                    className="absolute h-2.5 w-2.5 border border-white"
                    style={{
                      background: color,
                      cursor: `${corner}-resize`,
                      left: corner.includes("w") ? "-5px" : undefined,
                      right: corner.includes("e") ? "-5px" : undefined,
                      top: corner.includes("n") ? "-5px" : undefined,
                      bottom: corner.includes("s") ? "-5px" : undefined,
                    }}
                  />
                ))}
            </div>
          );
        })}
      </div>

      <div className="flex flex-col">
        {regions.map((region, index) => (
          <div
            key={index}
            className={cn(
              "border-b border-panel-line py-1.5 last:border-b-0",
              selected === index && "bg-ink-black/5",
            )}
          >
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setSelected(selected === index ? null : index)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
              >
                <span
                  className="h-2.5 w-2.5 flex-shrink-0 border border-ink-black/20"
                  style={{ background: regionColor(index) }}
                />
                <EditableText
                  value={region.label}
                  onSave={(v) => patchRegion(index, { label: v.trim() })}
                  className="font-display text-[0.78rem] font-bold tracking-[-0.02em]"
                />
                {region.reference_key && (
                  <span className="font-meta text-[0.52rem] tracking-[0.12em] text-archive-sage">
                    ◈ {region.reference_key.toUpperCase()}
                  </span>
                )}
              </button>
              <button
                type="button"
                onClick={() => removeRegion(index)}
                className="font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/40 hover:text-hero-red"
                title="Remove region"
              >
                REMOVE
              </button>
            </div>
            <div className="pl-4">
              <EditableText
                value={region.prompt}
                onSave={(v) => patchRegion(index, { prompt: v })}
                multiline
                className="w-full text-[0.75rem] leading-5 text-ink-black/80"
              />
              <div className="font-mono text-[0.6rem] text-ink-black/35">
                [{region.bbox.x0.toFixed(2)}, {region.bbox.y0.toFixed(2)}] → [
                {region.bbox.x1.toFixed(2)}, {region.bbox.y1.toFixed(2)}]
              </div>
            </div>
          </div>
        ))}
        <button
          type="button"
          onClick={addRegion}
          className="mt-2 self-start border-[2px] border-panel-line px-2 py-1 font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/60 hover:border-ink-black hover:text-ink-black"
        >
          + ADD REGION
        </button>
      </div>
    </div>
  );
}

/** Collapsible wrapper used by the prompt tab; hidden when no layout exists. */
export function LayoutSection({
  layout,
  imageUrl,
  aspectRatio,
  onChange,
}: {
  layout: PromptLayout | null | undefined;
  imageUrl?: string | null;
  aspectRatio: number;
  onChange: (layout: PromptLayout | null) => void;
}) {
  if (!layout || !layout.regions?.length) return null;
  return (
    <CollapsibleSection
      title={`Layout regions (${layout.regions.length})`}
      defaultExpanded
      storageKey="prompt-layout-regions"
      actions={
        <button
          type="button"
          onClick={() => onChange(null)}
          className="font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/40 hover:text-hero-red"
          title="Remove the layout — the panel regenerates from the flat prompt and the layout pass rebuilds regions on the next draw"
        >
          RESET
        </button>
      }
    >
      <LayoutRegionEditor
        layout={layout}
        imageUrl={imageUrl}
        aspectRatio={aspectRatio}
        onChange={onChange}
      />
    </CollapsibleSection>
  );
}

function nextLabel(regions: LayoutRegion[]): string {
  const taken = new Set(regions.map((r) => r.label));
  let i = regions.length + 1;
  while (taken.has(`region_${i}`)) i += 1;
  return `region_${i}`;
}

function round4(v: number) {
  return Math.round(clamp01(v) * 10000) / 10000;
}

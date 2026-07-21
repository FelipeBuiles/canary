import { useRef, useState } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { FieldLabel, SelectField, TextField } from "../ui/Field";
import { SurfaceHeader } from "../ui/Surface";
import type { ComicPage, Bubble, Sfx, PagePanel } from "../../types/api";
import { EditableText } from "../ui/EditableText";
import { useShowDevContent } from "../../lib/devContent";
import { resolveThemeVars } from "./themes";

/**
 * The original prose this caption was lettered from — valuable provenance,
 * clamped to two lines so it never dwarfs the editable text. Beat IDs are
 * machinery and stay behind Dev Content.
 */
function SourcePassage({ bubble }: { bubble: Bubble }) {
  const [expanded, setExpanded] = useState(false);
  const [showDevContent] = useShowDevContent();
  return (
    <div className="border-[2px] border-narrator-gold/35 bg-chip-gold/20 px-3 py-2">
      <div className="font-meta text-[0.55rem] font-bold tracking-[0.14em] text-narrator-gold uppercase">
        Source passage
      </div>
      {showDevContent && (
        <div className="mt-1 text-[0.72rem] leading-5 text-ink-fade">
          {bubble.source_beat_id}
          {bubble.narration_mode ? ` · ${bubble.narration_mode.replace(/_/g, " ")}` : ""}
          {bubble.preferred_zone ? ` · ${bubble.preferred_zone.replace(/_/g, " ")}` : ""}
        </div>
      )}
      {bubble.source_text && bubble.source_text !== bubble.text && (
        <>
          <div className={`mt-1 text-[0.72rem] italic leading-5 text-ink-black/65 ${expanded ? "" : "line-clamp-2"}`}>
            "{bubble.source_text}"
          </div>
          {bubble.source_text.length > 120 && (
            <button
              type="button"
              onClick={() => setExpanded((e) => !e)}
              className="mt-1 font-meta text-[0.5rem] tracking-[0.12em] text-ink-black/45 transition-colors hover:text-ink-black"
            >
              {expanded ? "HIDE FULL PASSAGE ▴" : "SHOW FULL PASSAGE ▾"}
            </button>
          )}
        </>
      )}
    </div>
  );
}

interface PropertyPanelProps {
  page: ComicPage;
  selection: { panelId: string; type: "bubble" | "sfx"; elementId: string } | null;
  panelReframeId: string | null;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onUpdateSfx: (panelId: string, sfxIndex: number, patch: Partial<Sfx>) => void;
  onDeleteElement: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onUnpin: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onCenterPanelFrame: (panelId: string) => void;
  onResetPanelFrame: (panelId: string) => void;
  onPreviewPanelScale: (panelId: string, scale: number) => void;
  onCommitPanelScale: (panelId: string, scale: number) => void;
}

function parseSfxIndexFromId(elementId: string): number {
  const m = elementId.match(/__sfx__(\d+)$/);
  return m ? Number(m[1]) : 0;
}

/**
 * Parse a numeric field into a clamped integer, or null to clear the
 * override. The backend stores these as ints — fractional or out-of-range
 * values would be rejected by the PATCH validation.
 */
function intInRange(raw: string, min: number, max: number): number | null {
  if (!raw) return null;
  const n = Number(raw);
  if (Number.isNaN(n)) return null;
  return Math.min(max, Math.max(min, Math.round(n)));
}

const BUBBLE_TYPES = ["speech", "thought", "narration"] as const;
const SIDES = ["left", "right", "center"] as const;
const FONT_OPTIONS = [
  { label: "Theme default", value: "" },
  { label: "Comic Neue", value: "'ComicNeue', 'Comic Neue', 'Comic Sans MS', cursive, sans-serif" },
  { label: "Bangers", value: "'Bangers', 'Anton', 'Impact', 'Arial Narrow Bold', sans-serif" },
  { label: "System Sans", value: "Arial, Helvetica, sans-serif" },
  { label: "Serif", value: "Georgia, serif" },
  { label: "Mono", value: "'Courier New', monospace" },
];

function DebouncedColorInput({ value, onCommit }: { value: string; onCommit: (v: string) => void }) {
  const [local, setLocal] = useState(value);
  const timerRef = useRef<number | null>(null);

  function schedule(next: string) {
    if (timerRef.current != null) clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => { onCommit(next); timerRef.current = null; }, 180);
  }

  return (
    <input
      type="color"
      value={local}
      onChange={(e) => { setLocal(e.target.value); schedule(e.target.value); }}
      onBlur={() => { if (local !== value) onCommit(local); }}
      className="ui-field h-[36px] p-1"
    />
  );
}

function findBubble(page: ComicPage, panelId: string, bubbleId: string) {
  const panel = page.panels.find((p) => p.id === panelId);
  if (!panel) return null;
  const bubble = panel.bubbles.find((b) => b.id === bubbleId);
  if (!bubble) return null;
  return { panel, bubble };
}

function findSfx(page: ComicPage, panelId: string, elementId: string) {
  const panel = page.panels.find((p) => p.id === panelId);
  if (!panel || panel.sfx.length === 0) return null;
  const idx = parseSfxIndexFromId(elementId);
  const sfx = panel.sfx[idx];
  if (!sfx) return null;
  return { panel, sfx, index: idx };
}

export function PropertyPanel({
  page,
  selection,
  panelReframeId,
  onUpdateBubble,
  onUpdateSfx,
  onDeleteElement,
  onUnpin,
  onCenterPanelFrame,
  onResetPanelFrame,
  onPreviewPanelScale,
  onCommitPanelScale,
}: PropertyPanelProps) {
  // Panel reframe inspector
  if (!selection && panelReframeId) {
    const panelIdx = page.panels.findIndex((p) => p.id === panelReframeId);
    const panel = page.panels[panelIdx];
    if (!panel) return null;
    return <PanelReframeInspector
      key={panel.id}
      panel={panel}
      panelIndex={panelIdx}
      onPreviewScale={onPreviewPanelScale}
      onCommitScale={onCommitPanelScale}
      onCenter={() => onCenterPanelFrame(panelReframeId)}
      onReset={() => onResetPanelFrame(panelReframeId)}
    />;
  }

  if (!selection) return null;

  if (selection.type === "bubble") {
    const found = findBubble(page, selection.panelId, selection.elementId);
    if (!found) return null;
    return (
      <BubbleInspector
        panel={found.panel}
        bubble={found.bubble}
        panelId={selection.panelId}
        onUpdate={(patch) => onUpdateBubble(selection.panelId, found.bubble.id, patch)}
        onUnpin={() => onUnpin(selection.panelId, "bubble", found.bubble.id)}
        onDelete={() => onDeleteElement(selection.panelId, "bubble", found.bubble.id)}
      />
    );
  }

  const sfxFound = findSfx(page, selection.panelId, selection.elementId);
  if (!sfxFound) return null;
  return (
    <SfxInspector
      panel={sfxFound.panel}
      sfx={sfxFound.sfx}
      sfxIndex={sfxFound.index}
      panelId={selection.panelId}
      elementId={selection.elementId}
      onUpdate={(patch) => onUpdateSfx(selection.panelId, sfxFound.index, patch)}
      onUnpin={() => onUnpin(selection.panelId, "sfx", selection.elementId)}
      onDelete={() => onDeleteElement(selection.panelId, "sfx", selection.elementId)}
    />
  );
}

function PanelReframeInspector({
  panel,
  panelIndex,
  onPreviewScale,
  onCommitScale,
  onCenter,
  onReset,
}: {
  panel: PagePanel;
  panelIndex: number;
  onPreviewScale: (panelId: string, scale: number) => void;
  onCommitScale: (panelId: string, scale: number) => void;
  onCenter: () => void;
  onReset: () => void;
}) {
  const persistedZoom = panel.image_scale ?? 1;
  const [zoom, setZoom] = useState(persistedZoom);
  const zoomRef = useRef(persistedZoom);
  const committedZoomRef = useRef<number | null>(null);
  const hasOffset = panel.image_offset_x != null || panel.image_offset_y != null;
  const hasCustomFrame = hasOffset || panel.image_scale != null;

  function previewZoom(raw: number) {
    const nextZoom = Math.min(2.5, Math.max(1, Number(raw.toFixed(2))));
    zoomRef.current = nextZoom;
    setZoom(nextZoom);
    onPreviewScale(panel.id, nextZoom);
  }

  function commitZoom() {
    const nextZoom = zoomRef.current;
    if (committedZoomRef.current === nextZoom) return;
    committedZoomRef.current = nextZoom;
    onCommitScale(panel.id, nextZoom);
  }

  function resetFrame() {
    zoomRef.current = 1;
    setZoom(1);
    committedZoomRef.current = 1;
    onPreviewScale(panel.id, 1);
    onReset();
  }

  return (
    <Card className="overflow-hidden shadow-[3px_3px_0_0_var(--color-ink-black)]">
      <SurfaceHeader kicker="CANVAS" title={`PANEL ${panelIndex + 1} · REFRAME`} />
      <div className="space-y-4 p-3">
        <p className="text-[0.72rem] leading-snug text-ink-black/50">
          Drag on the panel to pan the art. Use zoom to tighten the crop. Escape to exit.
        </p>

        <div>
          <FieldLabel htmlFor={`panel-zoom-${panel.id}`}>
            ZOOM <span className="ml-1 text-ink-black/35">· {Math.round(zoom * 100)}%</span>
          </FieldLabel>
          <input
            id={`panel-zoom-${panel.id}`}
            type="range"
            min="1"
            max="2.5"
            step="0.05"
            value={zoom}
            aria-label="Panel image zoom"
            onChange={(event) => previewZoom(Number(event.target.value))}
            onPointerUp={commitZoom}
            onPointerCancel={commitZoom}
            onKeyUp={(event) => {
              if (["ArrowDown", "ArrowLeft", "ArrowRight", "ArrowUp", "End", "Home", "PageDown", "PageUp"].includes(event.key)) {
                commitZoom();
              }
            }}
            onBlur={commitZoom}
            className="mt-2 w-full cursor-pointer accent-hero-red"
          />
          <div className="mt-1 flex justify-between font-meta text-[0.48rem] tracking-[0.1em] text-ink-black/35">
            <span>100%</span>
            <span>250%</span>
          </div>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <Button variant="secondary" size="xs" disabled={!hasOffset} onClick={onCenter}>
            CENTER IMAGE
          </Button>
          <Button variant="outline" size="xs" disabled={!hasCustomFrame} onClick={resetFrame}>
            RESET FRAMING
          </Button>
        </div>
      </div>
    </Card>
  );
}

function BubbleInspector({
  panel,
  bubble,
  onUpdate,
  onUnpin,
  onDelete,
}: {
  panel: PagePanel;
  bubble: Bubble;
  panelId: string;
  onUpdate: (patch: Partial<Bubble>) => void;
  onUnpin: () => void;
  onDelete: () => void;
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const isPinned = bubble.x != null && bubble.y != null;

  const tv = resolveThemeVars("default");
  const themeFs = parseInt(tv["--bubble-font-size"] ?? "44");
  const themeBorder = parseInt(tv["--bubble-border-width"] ?? "2");

  const effectiveFs = bubble.font_size ?? themeFs;
  const effectiveBorder = bubble.border_width ?? themeBorder;

  return (
    <Card className="max-h-none overflow-hidden shadow-[3px_3px_0_0_var(--color-ink-black)]">
      <SurfaceHeader kicker={`PANEL ${panel.panel_number} · ${bubble.type.toUpperCase()}`} title="BUBBLE" />

      <div className="max-h-[calc(100vh-200px)] space-y-3 overflow-y-auto p-3">
        <div>
          <FieldLabel>TEXT</FieldLabel>
          <EditableText
            value={bubble.text}
            onSave={(text) => onUpdate({ text })}
            multiline
            inputClassName="ui-field min-h-[60px]"
          />
        </div>

        {bubble.type === "narration" && bubble.source_beat_id && (
          <SourcePassage bubble={bubble} />
        )}

        <div className="grid grid-cols-2 gap-2">
          <div>
            <FieldLabel>TYPE</FieldLabel>
            <SelectField
              value={bubble.type}
              onChange={(e) => onUpdate({ type: e.target.value as typeof bubble.type })}
            >
              {BUBBLE_TYPES.map((t) => (
                <option key={t} value={t}>{t.toUpperCase()}</option>
              ))}
            </SelectField>
          </div>
          <div>
            <FieldLabel>SIDE</FieldLabel>
            <SelectField
              value={bubble.side}
              onChange={(e) => onUpdate({ side: e.target.value as typeof bubble.side })}
            >
              {SIDES.map((s) => (
                <option key={s} value={s}>{s.toUpperCase()}</option>
              ))}
            </SelectField>
          </div>
        </div>

        <label className="flex items-center gap-2 cursor-pointer select-none">
          <input
            type="checkbox"
            checked={bubble.full_width === true}
            onChange={(e) => onUpdate({ full_width: e.target.checked || null })}
            className="accent-[var(--color-ink-black)] w-3.5 h-3.5"
          />
          <span className="font-meta text-[0.6rem] tracking-[0.1em] text-ink-black/60">FULL WIDTH</span>
        </label>

        {isPinned && (
          <div>
            <div className="mb-1 font-meta text-[0.55rem] tracking-[0.12em] text-ink-black/40">
              PINNED · ({Math.round(bubble.x!)}, {Math.round(bubble.y!)})
            </div>
            <Button variant="secondary" size="xs" onClick={onUnpin}>UNPIN (AUTO)</Button>
          </div>
        )}

        {bubble.type !== "narration" && (
          <div>
            <div className="mb-1 font-meta text-[0.55rem] tracking-[0.12em] text-ink-black/40">
              {bubble.tail_x != null && bubble.tail_y != null
                ? `SPEAKER TARGET · (${Math.round(bubble.tail_x)}, ${Math.round(bubble.tail_y)})`
                : "SPEAKER TARGET · AUTO"}
            </div>
            <div className="flex items-center gap-2">
              <span className="font-meta text-[0.52rem] tracking-[0.08em] text-ink-black/55">
                DRAG THE RED TARGET ON THE PAGE
              </span>
              {bubble.tail_x != null && bubble.tail_y != null && (
                <Button
                  variant="secondary"
                  size="xs"
                  onClick={() => onUpdate({ tail_x: null, tail_y: null })}
                >
                  RESET
                </Button>
              )}
            </div>
          </div>
        )}

        {/* Advanced style toggle */}
        <div className="border-t border-ink-black/10 pt-2">
          <button
            type="button"
            onClick={() => setAdvancedOpen((o) => !o)}
            className="flex w-full items-center justify-between font-meta text-[0.55rem] tracking-[0.12em] text-ink-black/50 hover:text-ink-black/80"
          >
            <span>STYLE OVERRIDES</span>
            <span>{advancedOpen ? "▴" : "▾"}</span>
          </button>

          {advancedOpen && (
            <div className="mt-3 space-y-3">
              <div>
                <FieldLabel>FONT</FieldLabel>
                <SelectField
                  value={bubble.font_family ?? ""}
                  onChange={(e) => onUpdate({ font_family: e.target.value || null })}
                >
                  {FONT_OPTIONS.map((f) => (
                    <option key={f.label} value={f.value}>{f.label.toUpperCase()}</option>
                  ))}
                </SelectField>
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <FieldLabel>
                    SIZE
                    <span className="ml-1 text-ink-black/35">· {effectiveFs}px</span>
                  </FieldLabel>
                  <TextField
                    type="number"
                    value={bubble.font_size ?? ""}
                    placeholder={String(themeFs)}
                    min={8}
                    max={96}
                    onChange={(e) => onUpdate({ font_size: intInRange(e.target.value, 8, 96) })}
                  />
                </div>
                <div>
                  <FieldLabel>
                    BORDER
                    <span className="ml-1 text-ink-black/35">· {effectiveBorder}px</span>
                  </FieldLabel>
                  <TextField
                    type="number"
                    value={bubble.border_width ?? ""}
                    placeholder={String(themeBorder)}
                    min={0}
                    max={16}
                    onChange={(e) => onUpdate({ border_width: intInRange(e.target.value, 0, 16) })}
                  />
                </div>
              </div>

              <div className="grid grid-cols-3 gap-2">
                <div>
                  <FieldLabel>TEXT</FieldLabel>
                  <DebouncedColorInput
                    value={bubble.font_color ?? "#1A1A1A"}
                    onCommit={(v) => onUpdate({ font_color: v })}
                  />
                </div>
                <div>
                  <FieldLabel>FILL</FieldLabel>
                  <DebouncedColorInput
                    value={bubble.fill_color ?? "#FFFFFF"}
                    onCommit={(v) => onUpdate({ fill_color: v })}
                  />
                </div>
                <div>
                  <FieldLabel>STROKE</FieldLabel>
                  <DebouncedColorInput
                    value={bubble.border_color ?? "#1A1A1A"}
                    onCommit={(v) => onUpdate({ border_color: v })}
                  />
                </div>
              </div>

              <Button
                variant="secondary"
                size="sm"
                onClick={() => onUpdate({
                  font_family: null,
                  font_size: null,
                  font_color: null,
                  fill_color: null,
                  border_color: null,
                  border_width: null,
                })}
              >
                RESET TO THEME
              </Button>
            </div>
          )}
        </div>

        <div className="border-t border-ink-black/10 pt-2">
          <Button variant="outline" size="sm" onClick={onDelete}>DELETE BUBBLE</Button>
        </div>
      </div>
    </Card>
  );
}

const SFX_KINDS = ["impact", "mechanical", "voice", "ambient", "environment"] as const;
const SFX_INTENSITIES = [1, 2, 3] as const;
const SFX_ANCHORS = [
  "auto",
  "bottom-center",
  "top-center",
  "bottom-left",
  "bottom-right",
  "top-left",
  "top-right",
] as const;

function SfxInspector({
  panel,
  sfx,
  sfxIndex,
  onUpdate,
  onUnpin,
  onDelete,
}: {
  panel: PagePanel;
  sfx: Sfx;
  sfxIndex: number;
  panelId: string;
  elementId: string;
  onUpdate: (patch: Partial<Sfx>) => void;
  onUnpin: () => void;
  onDelete: () => void;
}) {
  const isPinned = sfx.x != null && sfx.y != null;
  const totalSfx = panel.sfx.length;

  return (
    <Card className="overflow-hidden shadow-[3px_3px_0_0_var(--color-ink-black)]">
      <SurfaceHeader
        kicker={`PANEL ${panel.panel_number}`}
        title={totalSfx > 1 ? `SFX ${sfxIndex + 1}/${totalSfx}` : "SFX"}
      />

      <div className="space-y-3 p-3">
        <div>
          <FieldLabel>TEXT</FieldLabel>
          <EditableText
            value={sfx.text}
            onSave={(text) => onUpdate({ text })}
            inputClassName="ui-field"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <FieldLabel>KIND</FieldLabel>
            <SelectField
              value={sfx.kind ?? "impact"}
              onChange={(e) => onUpdate({ kind: e.target.value as Sfx["kind"] })}
            >
              {SFX_KINDS.map((k) => (
                <option key={k} value={k}>{k.toUpperCase()}</option>
              ))}
            </SelectField>
          </div>
          <div>
            <FieldLabel>INTENSITY</FieldLabel>
            <SelectField
              value={String(sfx.intensity ?? 2)}
              onChange={(e) => onUpdate({ intensity: Number(e.target.value) as Sfx["intensity"] })}
            >
              {SFX_INTENSITIES.map((n) => (
                <option key={n} value={n}>{n} ({["quiet", "medium", "big"][n - 1]})</option>
              ))}
            </SelectField>
          </div>
        </div>

        {!isPinned && (
          <div>
            <FieldLabel>ANCHOR</FieldLabel>
            <SelectField
              value={sfx.anchor ?? "auto"}
              onChange={(e) => onUpdate({ anchor: e.target.value as Sfx["anchor"] })}
            >
              {SFX_ANCHORS.map((a) => (
                <option key={a} value={a}>{a.toUpperCase()}</option>
              ))}
            </SelectField>
          </div>
        )}

        <div className="grid grid-cols-2 gap-2">
          <div>
            <FieldLabel>ROTATION</FieldLabel>
            <TextField
              type="number"
              value={sfx.rotation}
              step={1}
              onChange={(e) => {
                const n = Number(e.target.value);
                if (!Number.isNaN(n)) onUpdate({ rotation: n });
              }}
            />
          </div>
          <div>
            <FieldLabel>FONT SIZE</FieldLabel>
            <TextField
              type="number"
              value={sfx.font_size ?? ""}
              placeholder="Auto"
              min={8}
              max={200}
              onChange={(e) => onUpdate({ font_size: intInRange(e.target.value, 8, 200) })}
            />
          </div>
        </div>

        {isPinned && (
          <div>
            <div className="mb-1 font-meta text-[0.55rem] tracking-[0.12em] text-ink-black/40">
              PINNED · ({Math.round(sfx.x!)}, {Math.round(sfx.y!)})
            </div>
            <Button variant="secondary" size="xs" onClick={onUnpin}>UNPIN (AUTO)</Button>
          </div>
        )}

        <div className="border-t border-ink-black/10 pt-2">
          <Button variant="outline" size="sm" onClick={onDelete}>DELETE SFX</Button>
        </div>
      </div>
    </Card>
  );
}

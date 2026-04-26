import { useRef, useState } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { FieldLabel, SelectField, TextField } from "../ui/Field";
import { SurfaceHeader } from "../ui/Surface";
import type { ComicPage, Bubble, Sfx, PagePanel } from "../../types/api";
import { EditableText } from "../ui/EditableText";
import { resolveThemeVars } from "./themes";

interface PropertyPanelProps {
  page: ComicPage;
  selection: { panelId: string; type: "bubble" | "sfx"; elementId: string } | null;
  panelReframeId: string | null;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onUpdateSfx: (panelId: string, patch: Partial<Sfx>) => void;
  onDeleteElement: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onUnpin: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onResetPanelFrame: (panelId: string) => void;
}

const BUBBLE_TYPES = ["speech", "thought", "narration"] as const;
const SIDES = ["left", "right", "center"] as const;
const FONT_OPTIONS = [
  { label: "Theme default", value: "" },
  { label: "Comic Neue", value: "'ComicNeue', 'Comic Neue', 'Comic Sans MS', cursive, sans-serif" },
  { label: "Bangers", value: "'Bangers', 'Arial Narrow', fantasy, sans-serif" },
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

function findSfx(page: ComicPage, panelId: string) {
  const panel = page.panels.find((p) => p.id === panelId);
  if (!panel?.sfx) return null;
  return { panel, sfx: panel.sfx };
}

export function PropertyPanel({
  page,
  selection,
  panelReframeId,
  onUpdateBubble,
  onUpdateSfx,
  onDeleteElement,
  onUnpin,
  onResetPanelFrame,
}: PropertyPanelProps) {
  // Panel reframe inspector
  if (!selection && panelReframeId) {
    const panelIdx = page.panels.findIndex((p) => p.id === panelReframeId);
    const panel = page.panels[panelIdx];
    const hasOffset = panel && (panel.image_offset_x != null || panel.image_offset_y != null);
    return (
      <Card className="overflow-hidden shadow-[3px_3px_0_0_var(--color-ink-black)]">
        <SurfaceHeader kicker="CANVAS" title={`PANEL ${panelIdx + 1} · REFRAME`} />
        <div className="space-y-3 p-3">
          <p className="text-[0.72rem] leading-snug text-ink-black/50">
            Drag on the panel to shift the image. Escape to exit.
          </p>
          {hasOffset && (
            <Button variant="secondary" size="sm" onClick={() => onResetPanelFrame(panelReframeId)}>
              RESET FRAMING
            </Button>
          )}
        </div>
      </Card>
    );
  }

  if (!selection) return null;

  if (selection.type === "bubble") {
    const found = findBubble(page, selection.panelId, selection.elementId);
    if (!found) return null;
    return (
      <BubbleInspector
        page={page}
        panel={found.panel}
        bubble={found.bubble}
        panelId={selection.panelId}
        onUpdate={(patch) => onUpdateBubble(selection.panelId, found.bubble.id, patch)}
        onUnpin={() => onUnpin(selection.panelId, "bubble", found.bubble.id)}
        onDelete={() => onDeleteElement(selection.panelId, "bubble", found.bubble.id)}
      />
    );
  }

  const sfxFound = findSfx(page, selection.panelId);
  if (!sfxFound) return null;
  return (
    <SfxInspector
      panel={sfxFound.panel}
      sfx={sfxFound.sfx}
      panelId={selection.panelId}
      elementId={selection.elementId}
      onUpdate={(patch) => onUpdateSfx(selection.panelId, patch)}
      onUnpin={() => onUnpin(selection.panelId, "sfx", selection.elementId)}
      onDelete={() => onDeleteElement(selection.panelId, "sfx", selection.elementId)}
    />
  );
}

function BubbleInspector({
  page,
  panel,
  bubble,
  onUpdate,
  onUnpin,
  onDelete,
}: {
  page: ComicPage;
  panel: PagePanel;
  bubble: Bubble;
  panelId: string;
  onUpdate: (patch: Partial<Bubble>) => void;
  onUnpin: () => void;
  onDelete: () => void;
}) {
  const [advancedOpen, setAdvancedOpen] = useState(false);
  const isPinned = bubble.x != null && bubble.y != null;

  const tv = resolveThemeVars(page.theme ?? "default");
  const themeFs = parseInt(tv["--bubble-font-size"] ?? "36");
  const themeRadius = parseInt(tv["--bubble-radius"] ?? "14");
  const themeBorder = parseInt(tv["--bubble-border-width"] ?? "2");

  const effectiveFs = bubble.font_size ?? themeFs;
  const effectiveRadius = bubble.border_radius ?? themeRadius;
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

              <div className="grid grid-cols-3 gap-2">
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
                    onChange={(e) => onUpdate({ font_size: e.target.value ? Number(e.target.value) : null })}
                  />
                </div>
                <div>
                  <FieldLabel>
                    RADIUS
                    <span className="ml-1 text-ink-black/35">· {effectiveRadius}px</span>
                  </FieldLabel>
                  <TextField
                    type="number"
                    value={bubble.border_radius ?? ""}
                    placeholder={String(themeRadius)}
                    min={0}
                    max={120}
                    onChange={(e) => onUpdate({ border_radius: e.target.value ? Number(e.target.value) : null })}
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
                    onChange={(e) => onUpdate({ border_width: e.target.value ? Number(e.target.value) : null })}
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
                  border_radius: null,
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

function SfxInspector({
  panel,
  sfx,
  onUpdate,
  onUnpin,
  onDelete,
}: {
  panel: PagePanel;
  sfx: Sfx;
  panelId: string;
  elementId: string;
  onUpdate: (patch: Partial<Sfx>) => void;
  onUnpin: () => void;
  onDelete: () => void;
}) {
  const isPinned = sfx.x != null && sfx.y != null;

  return (
    <Card className="overflow-hidden shadow-[3px_3px_0_0_var(--color-ink-black)]">
      <SurfaceHeader kicker={`PANEL ${panel.panel_number}`} title="SFX" />

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
            <FieldLabel>ROTATION</FieldLabel>
            <TextField
              type="number"
              value={sfx.rotation}
              step={1}
              onChange={(e) => onUpdate({ rotation: Number(e.target.value) })}
            />
          </div>
          <div>
            <FieldLabel>FONT SIZE</FieldLabel>
            <TextField
              type="number"
              value={sfx.font_size ?? ""}
              placeholder="Auto"
              onChange={(e) => onUpdate({ font_size: e.target.value ? Number(e.target.value) : null })}
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

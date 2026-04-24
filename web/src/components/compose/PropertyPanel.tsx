import { useEffect, useRef, useState } from "react";
import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import { FieldLabel, SelectField, TextField } from "../ui/Field";
import { SurfaceHeader } from "../ui/Surface";
import type { ComicPage, Bubble, Sfx, PagePanel } from "../../types/api";
import { EditableText } from "../ui/EditableText";
import { useI18n } from "../../i18n";

interface PropertyPanelProps {
  page: ComicPage;
  selection: { panelId: string; type: "bubble" | "sfx"; elementId: string } | null;
  onUpdatePanel: (panelId: string, patch: Partial<PagePanel>) => void;
  onUpdatePanelStructure: (
    plannedPanelId: string,
    patch: { importance?: string | null; shape_intent?: string | null; generation_mode?: string | null },
  ) => void;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onUpdateSfx: (panelId: string, patch: Partial<Sfx>) => void;
  onUpdatePage: (patch: Partial<ComicPage>) => void;
  onReflowPages: (panelsPerPage: number) => void;
  onGeneratePageStyle: () => void;
  outputLanguage: "en" | "es" | "fr";
  onOutputLanguageChange: (language: "en" | "es" | "fr") => void;
  onTranslateBubbles: (language: "en" | "es" | "fr") => void;
  isGeneratingPageStyle?: boolean;
  isTranslatingBubbles?: boolean;
  onDeleteElement: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onUnpin: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
}

const THEMES = ["default", "noir", "manga", "vintage", "painted"];
const PANELS_PER_PAGE = [1, 2, 3, 4, 5, 6];
const BUBBLE_TYPES = ["speech", "thought", "narration"] as const;
const SIDES = ["left", "right", "center"] as const;
const PANEL_IMPORTANCE_OPTIONS = ["standard", "accent", "hero", "splash", "inset"] as const;
const PANEL_SHAPE_OPTIONS = ["rect", "wide", "tall", "panorama", "bleed", "irregular"] as const;
const GENERATION_MODE_OPTIONS = ["master", "exact"] as const;
const FONT_OPTIONS = [
  { label: "Comic Neue", value: "'ComicNeue', 'Comic Neue', 'Comic Sans MS', cursive, sans-serif" },
  { label: "Bangers", value: "'Bangers', 'Arial Narrow', fantasy, sans-serif" },
  { label: "System Sans", value: "Arial, Helvetica, sans-serif" },
  { label: "Serif", value: "Georgia, serif" },
  { label: "Mono", value: "'Courier New', monospace" },
];

function BindingIndicator({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "active";
}) {
  return (
    <div className={`border px-2 py-1.5 ${tone === "active" ? "border-hero-red/45 bg-outline-ghost/45" : "border-ink-black/12 bg-bristol"}`}>
      <div className="font-meta text-[0.45rem] tracking-[0.18em] text-ink-black/38">{label}</div>
      <div className="mt-0.5 font-meta text-[0.58rem] tracking-[0.12em] text-ink-black/70">{value}</div>
    </div>
  );
}

interface DebouncedColorInputProps {
  value: string;
  onCommit: (value: string) => void;
}

function DebouncedColorInput({ value, onCommit }: DebouncedColorInputProps) {
  const [localValue, setLocalValue] = useState(value);
  const timeoutRef = useRef<number | null>(null);

  useEffect(() => {
    setLocalValue(value);
  }, [value]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current != null) window.clearTimeout(timeoutRef.current);
    };
  }, []);

  function scheduleCommit(nextValue: string) {
    if (nextValue === value) return;
    if (timeoutRef.current != null) window.clearTimeout(timeoutRef.current);
    timeoutRef.current = window.setTimeout(() => {
      onCommit(nextValue);
      timeoutRef.current = null;
    }, 180);
  }

  function flushCommit() {
    if (timeoutRef.current != null) {
      window.clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
    if (localValue === value) return;
    onCommit(localValue);
  }

  return (
    <input
      type="color"
      value={localValue}
      onChange={(e) => {
        const nextValue = e.target.value;
        setLocalValue(nextValue);
        scheduleCommit(nextValue);
      }}
      onBlur={flushCommit}
      onPointerUp={flushCommit}
      className="ui-field h-[36px] p-1"
    />
  );
}

function findBubble(page: ComicPage, panelId: string, bubbleId: string): { panel: PagePanel; bubble: Bubble } | null {
  const panel = page.panels.find((p) => p.id === panelId);
  if (!panel) return null;
  const bubble = panel.bubbles.find((b) => b.id === bubbleId);
  if (!bubble) return null;
  return { panel, bubble };
}

function findSfx(page: ComicPage, panelId: string): { panel: PagePanel; sfx: Sfx } | null {
  const panel = page.panels.find((p) => p.id === panelId);
  if (!panel?.sfx) return null;
  return { panel, sfx: panel.sfx };
}

export function PropertyPanel({
  page,
  selection,
  onUpdatePanel,
  onUpdatePanelStructure,
  onUpdateBubble,
  onUpdateSfx,
  onUpdatePage,
  onReflowPages,
  onGeneratePageStyle,
  outputLanguage,
  onOutputLanguageChange,
  onTranslateBubbles,
  isGeneratingPageStyle,
  isTranslatingBubbles,
  onDeleteElement,
  onUnpin,
}: PropertyPanelProps) {
  const { t } = useI18n();
  const [imagePanelId, setImagePanelId] = useState(page.panels[0]?.id ?? "");
  const imagePanel = page.panels.find((p) => p.id === imagePanelId) ?? page.panels[0];

  if (!selection) {
    return (
      <Card className="max-h-none overflow-hidden shadow-[3px_3px_0_0_var(--color-ink-black)] md:max-h-[calc(100vh-236px)]">
        <SurfaceHeader kicker="INSPECTOR" title={t("PAGE PROPERTIES")} />

        <div className="max-h-none space-y-4 overflow-y-auto p-3 md:max-h-[calc(100vh-292px)]">
        <div>
          <FieldLabel>{t("THEME")}</FieldLabel>
          <SelectField
            value={page.theme}
            onChange={(e) => onUpdatePage({ theme: e.target.value })}
          >
            {THEMES.map((t) => (
              <option key={t} value={t}>{t.toUpperCase()}</option>
            ))}
          </SelectField>
        </div>

        <div>
          <FieldLabel>{t("PANELS PER PAGE")}</FieldLabel>
          <SelectField
            value={page.panels.length}
            onChange={(e) => onReflowPages(Number(e.target.value))}
          >
            {PANELS_PER_PAGE.map((count) => (
              <option key={count} value={count}>{count} {count === 1 ? t("PANEL") : t("PANELS")} / {t("PAGE")}</option>
            ))}
          </SelectField>
          <p className="mt-1 text-[0.72rem] leading-snug text-ink-black/45">
            {t("Reflows every panel and updates the page count.")}
          </p>
        </div>

        <div className="ui-rule">
          <div className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/45">
            {page.panels.length} {t("PANELS")} / {t("PAGE")} {String(page.page_number).padStart(2, "0")}
          </div>
        </div>

        <div className="ui-rule space-y-2">
          <Button
            size="sm"
            variant="primary"
            onClick={onGeneratePageStyle}
            disabled={isGeneratingPageStyle}
            className="w-full"
          >
            {isGeneratingPageStyle ? t("MATCHING STYLE...") : t("MATCH LETTERING TO ART")}
          </Button>
          <p className="text-[0.72rem] leading-snug text-ink-black/45">
            {t("Generates page defaults for panel borders, narration, bubbles, and SFX from the active panel style.")}
          </p>
        </div>

        <div className="ui-rule space-y-2">
          <FieldLabel>
            {t("OUTPUT BUBBLE LANGUAGE")}
          </FieldLabel>
          <SelectField
            value={outputLanguage}
            onChange={(e) => onOutputLanguageChange(e.target.value as "en" | "es" | "fr")}
          >
            <option value="en">English (en)</option>
            <option value="es">Español (es)</option>
            <option value="fr">Français (fr)</option>
          </SelectField>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => onTranslateBubbles(outputLanguage)}
            disabled={isTranslatingBubbles}
            className="w-full"
          >
            {isTranslatingBubbles ? t("TRANSLATING...") : t("TRANSLATE EXISTING BUBBLES")}
          </Button>
          <p className="text-[0.72rem] leading-snug text-ink-black/45">
            {t("Translates assembled speech, thought, and narration text into the project output language.")}
          </p>
        </div>

        {imagePanel && (
          <div className="ui-rule space-y-2">
            <div className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/45">
              {t("PANEL IMAGE FRAMING")}
            </div>
            <SelectField
              value={imagePanel.id}
              onChange={(e) => setImagePanelId(e.target.value)}
            >
              {page.panels.map((panel, idx) => (
                <option key={panel.id} value={panel.id}>
                  {t("PANEL")} {idx + 1} ({panel.scene_id}/{panel.panel_number})
                </option>
              ))}
            </SelectField>

            <div className="grid grid-cols-2 gap-2">
              <div>
                <FieldLabel>X</FieldLabel>
                <TextField
                  type="number"
                  value={imagePanel.image_offset_x ?? 0}
                  min={-1200}
                  max={1200}
                  onChange={(e) => onUpdatePanel(imagePanel.id, {
                    image_offset_x: Number(e.target.value),
                  })}
                />
              </div>
              <div>
                <FieldLabel>Y</FieldLabel>
                <TextField
                  type="number"
                  value={imagePanel.image_offset_y ?? 0}
                  min={-1200}
                  max={1200}
                  onChange={(e) => onUpdatePanel(imagePanel.id, {
                    image_offset_y: Number(e.target.value),
                  })}
                />
              </div>
            </div>
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="xs"
                onClick={() => onUpdatePanel(imagePanel.id, {
                  image_offset_x: (imagePanel.image_offset_x ?? 0) - 20,
                })}
              >
                {t("LEFT")}
              </Button>
              <Button
                variant="secondary"
                size="xs"
                onClick={() => onUpdatePanel(imagePanel.id, {
                  image_offset_x: (imagePanel.image_offset_x ?? 0) + 20,
                })}
              >
                {t("RIGHT")}
              </Button>
              <Button
                variant="secondary"
                size="xs"
                onClick={() => onUpdatePanel(imagePanel.id, {
                  image_offset_y: (imagePanel.image_offset_y ?? 0) - 20,
                })}
              >
                {t("UP")}
              </Button>
              <Button
                variant="secondary"
                size="xs"
                onClick={() => onUpdatePanel(imagePanel.id, {
                  image_offset_y: (imagePanel.image_offset_y ?? 0) + 20,
                })}
              >
                {t("DOWN")}
              </Button>
              <Button
                variant="outline"
                size="xs"
                onClick={() => onUpdatePanel(imagePanel.id, {
                  image_offset_x: null,
                  image_offset_y: null,
                })}
              >
                {t("RESET")}
              </Button>
            </div>

            {imagePanel.planned_panel_id && (
              <div className="ui-rule space-y-2">
                <div className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/45">
                  {t("PLANNER OVERRIDES")}
                </div>
                <div>
                  <FieldLabel>{t("VISUAL EMPHASIS")}</FieldLabel>
                  <SelectField
                    value={imagePanel.importance ?? "standard"}
                    onChange={(e) => onUpdatePanelStructure(imagePanel.planned_panel_id!, {
                      importance: e.target.value,
                    })}
                  >
                    {PANEL_IMPORTANCE_OPTIONS.map((option) => (
                      <option key={option} value={option}>{option.toUpperCase()}</option>
                    ))}
                  </SelectField>
                </div>
                <div>
                  <FieldLabel>{t("PANEL SHAPE")}</FieldLabel>
                  <SelectField
                    value={imagePanel.shape_intent ?? "rect"}
                    onChange={(e) => onUpdatePanelStructure(imagePanel.planned_panel_id!, {
                      shape_intent: e.target.value,
                    })}
                  >
                    {PANEL_SHAPE_OPTIONS.map((option) => (
                      <option key={option} value={option}>{option.toUpperCase()}</option>
                    ))}
                  </SelectField>
                </div>
                <div>
                  <FieldLabel>{t("IMAGE FRAMING")}</FieldLabel>
                  <SelectField
                    value={imagePanel.generation_mode ?? "master"}
                    onChange={(e) => onUpdatePanelStructure(imagePanel.planned_panel_id!, {
                      generation_mode: e.target.value,
                    })}
                  >
                    {GENERATION_MODE_OPTIONS.map((option) => (
                      <option key={option} value={option}>{option.toUpperCase()}</option>
                    ))}
                  </SelectField>
                </div>
                <p className="text-[0.72rem] leading-snug text-ink-black/45">
                  {t("These edits write back to the layout plan, then reproject Compose. Existing images stay in place until you explicitly redraw affected panels.")}
                </p>
              </div>
            )}
          </div>
        )}

        <div className="text-[0.78rem] text-ink-black/40">
          {t("Click a bubble or SFX on the page to edit its properties.")}
        </div>
        </div>
      </Card>
    );
  }

  if (selection.type === "bubble") {
    const found = findBubble(page, selection.panelId, selection.elementId);
    if (!found) return null;
    const { bubble } = found;
    const isPinned = bubble.x != null && bubble.y != null;

    return (
      <Card className="max-h-none overflow-hidden shadow-[3px_3px_0_0_var(--color-ink-black)] md:max-h-[calc(100vh-236px)]">
        <SurfaceHeader kicker="INSPECTOR" title={t("BUBBLE")} />

        <div className="max-h-none space-y-4 overflow-y-auto p-3 md:max-h-[calc(100vh-292px)]">
        <div className="grid grid-cols-3 gap-1.5">
          <BindingIndicator label="PANEL" value={`P${found.panel.panel_number}`} tone="active" />
          <BindingIndicator label="ANCHOR" value={isPinned ? "PINNED" : "AUTO"} />
          <BindingIndicator label="TAIL" value={bubble.tail_x != null && bubble.tail_y != null ? "TARGET" : bubble.type === "speech" ? bubble.tail_direction.toUpperCase() : "NONE"} />
        </div>

        <div>
          <FieldLabel>{t("TEXT")}</FieldLabel>
          <EditableText
            value={bubble.text}
            onSave={(text) => onUpdateBubble(selection.panelId, bubble.id, { text })}
            multiline
            inputClassName="ui-field min-h-[60px]"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <FieldLabel>{t("TYPE")}</FieldLabel>
            <SelectField
              value={bubble.type}
              onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { type: e.target.value as typeof bubble.type })}
            >
              {BUBBLE_TYPES.map((t) => (
                <option key={t} value={t}>{t.toUpperCase()}</option>
              ))}
            </SelectField>
          </div>
          <div>
            <FieldLabel>{t("SIDE")}</FieldLabel>
            <SelectField
              value={bubble.side}
              onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { side: e.target.value as typeof bubble.side })}
            >
              {SIDES.map((s) => (
                <option key={s} value={s}>{s.toUpperCase()}</option>
              ))}
            </SelectField>
          </div>
        </div>

        <div>
          <FieldLabel>{t("WIDTH")}</FieldLabel>
          <div className="flex items-center gap-2">
            <TextField
              type="number"
              value={bubble.width ?? ""}
              placeholder="Auto"
              onChange={(e) => {
                const v = e.target.value ? Number(e.target.value) : null;
                onUpdateBubble(selection.panelId, bubble.id, { width: v });
              }}
            />
          </div>
        </div>

        <div className="ui-rule space-y-3">
          <div className="font-meta text-[0.65rem] tracking-[0.18em] text-ink-black/50">
            {t("BUBBLE STYLE")}
          </div>

          <div>
            <FieldLabel>FONT</FieldLabel>
            <SelectField
              value={bubble.font_family ?? ""}
              onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { font_family: e.target.value || null })}
            >
              <option value="">THEME DEFAULT</option>
              {FONT_OPTIONS.map((font) => (
                <option key={font.label} value={font.value}>{font.label.toUpperCase()}</option>
              ))}
            </SelectField>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <FieldLabel>FONT SIZE</FieldLabel>
              <TextField
                type="number"
                value={bubble.font_size ?? ""}
                placeholder="Auto"
                min={8}
                max={96}
                onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { font_size: e.target.value ? Number(e.target.value) : null })}
              />
            </div>
            <div>
              <FieldLabel>BORDER PX</FieldLabel>
              <TextField
                type="number"
                value={bubble.border_width ?? ""}
                placeholder="Auto"
                min={0}
                max={16}
                onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { border_width: e.target.value ? Number(e.target.value) : null })}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <FieldLabel>RADIUS</FieldLabel>
              <TextField
                type="number"
                value={bubble.border_radius ?? ""}
                placeholder="Auto"
                min={0}
                max={120}
                onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { border_radius: e.target.value ? Number(e.target.value) : null })}
              />
            </div>
            <div>
              <FieldLabel>TEXT</FieldLabel>
              <DebouncedColorInput
                value={bubble.font_color ?? "#1A1A1A"}
                onCommit={(value) => onUpdateBubble(selection.panelId, bubble.id, { font_color: value })}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <FieldLabel>FILL</FieldLabel>
              <DebouncedColorInput
                value={bubble.fill_color ?? "#FFFFFF"}
                onCommit={(value) => onUpdateBubble(selection.panelId, bubble.id, { fill_color: value })}
              />
            </div>
            <div>
              <FieldLabel>BORDER</FieldLabel>
              <DebouncedColorInput
                value={bubble.border_color ?? "#1A1A1A"}
                onCommit={(value) => onUpdateBubble(selection.panelId, bubble.id, { border_color: value })}
              />
            </div>
          </div>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => onUpdateBubble(selection.panelId, bubble.id, {
              font_family: null,
              font_size: null,
              font_color: null,
              fill_color: null,
              border_color: null,
              border_width: null,
              border_radius: null,
            })}
          >
            RESET STYLE
          </Button>
        </div>

        {isPinned && (
          <div className="space-y-1">
            <div className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/45">
              POSITION: ({Math.round(bubble.x!)}, {Math.round(bubble.y!)})
            </div>
            <Button
              variant="secondary"
              size="xs"
              onClick={() => onUnpin(selection.panelId, "bubble", bubble.id)}
            >
              UNPIN (AUTO)
            </Button>
          </div>
        )}

        <div className="ui-rule">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onDeleteElement(selection.panelId, "bubble", bubble.id)}
          >
            DELETE BUBBLE
          </Button>
        </div>
        </div>
      </Card>
    );
  }

  // SFX
  const sfxFound = findSfx(page, selection.panelId);
  if (!sfxFound) return null;
  const { sfx } = sfxFound;
  const sfxPinned = sfx.x != null && sfx.y != null;

  return (
      <Card className="max-h-none overflow-hidden shadow-[3px_3px_0_0_var(--color-ink-black)] md:max-h-[calc(100vh-236px)]">
      <SurfaceHeader kicker="INSPECTOR" title="SFX" />

      <div className="max-h-none space-y-4 overflow-y-auto p-3 md:max-h-[calc(100vh-292px)]">
      <div className="grid grid-cols-2 gap-1.5">
        <BindingIndicator label="PANEL" value={`P${sfxFound.panel.panel_number}`} tone="active" />
        <BindingIndicator label="ANCHOR" value={sfxPinned ? "PINNED" : "AUTO"} />
      </div>

      <div>
        <FieldLabel>TEXT</FieldLabel>
        <EditableText
          value={sfx.text}
          onSave={(text) => onUpdateSfx(selection.panelId, { text })}
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
            onChange={(e) => onUpdateSfx(selection.panelId, { rotation: Number(e.target.value) })}
          />
        </div>
        <div>
          <FieldLabel>FONT SIZE</FieldLabel>
          <TextField
            type="number"
            value={sfx.font_size ?? ""}
            placeholder="Auto"
            onChange={(e) => {
              const v = e.target.value ? Number(e.target.value) : null;
              onUpdateSfx(selection.panelId, { font_size: v });
            }}
          />
        </div>
      </div>

      {sfxPinned && (
        <div className="space-y-1">
          <div className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/45">
            POSITION: ({Math.round(sfx.x!)}, {Math.round(sfx.y!)})
          </div>
          <Button
            variant="secondary"
            size="xs"
            onClick={() => onUnpin(selection.panelId, "sfx", selection.elementId)}
          >
            UNPIN (AUTO)
          </Button>
        </div>
      )}

      <div className="ui-rule">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onDeleteElement(selection.panelId, "sfx", selection.elementId)}
        >
          DELETE SFX
        </Button>
      </div>
      </div>
    </Card>
  );
}

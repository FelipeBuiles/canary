import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import type { ComicPage, Bubble, Sfx, PagePanel } from "../../types/api";
import { EditableText } from "../ui/EditableText";
import { useI18n } from "../../i18n";

interface PropertyPanelProps {
  page: ComicPage;
  selection: { panelId: string; type: "bubble" | "sfx"; elementId: string } | null;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onUpdateSfx: (panelId: string, patch: Partial<Sfx>) => void;
  onUpdatePage: (patch: Partial<ComicPage>) => void;
  onReflowPages: (panelsPerPage: number) => void;
  onGeneratePageStyle: () => void;
  onTranslateBubbles: () => void;
  isGeneratingPageStyle?: boolean;
  isTranslatingBubbles?: boolean;
  onDeleteElement: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onUnpin: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
}

const THEMES = ["default", "noir", "manga", "vintage", "painted"];
const PANELS_PER_PAGE = [1, 2, 3, 4, 5, 6];
const BUBBLE_TYPES = ["speech", "thought", "narration"] as const;
const SIDES = ["left", "right", "center"] as const;
const FONT_OPTIONS = [
  { label: "Comic Neue", value: "'ComicNeue', 'Comic Neue', 'Comic Sans MS', cursive, sans-serif" },
  { label: "Bangers", value: "'Bangers', 'Arial Narrow', fantasy, sans-serif" },
  { label: "System Sans", value: "Arial, Helvetica, sans-serif" },
  { label: "Serif", value: "Georgia, serif" },
  { label: "Mono", value: "'Courier New', monospace" },
];

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
  onUpdateBubble,
  onUpdateSfx,
  onUpdatePage,
  onReflowPages,
  onGeneratePageStyle,
  onTranslateBubbles,
  isGeneratingPageStyle,
  isTranslatingBubbles,
  onDeleteElement,
  onUnpin,
}: PropertyPanelProps) {
  const { t } = useI18n();
  if (!selection) {
    return (
      <Card className="p-3 space-y-3">
        <div className="font-meta text-[0.65rem] tracking-[0.18em] text-ink-black/50">
          {t("PAGE PROPERTIES")}
        </div>

        <div>
          <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">{t("THEME")}</label>
          <select
            value={page.theme}
            onChange={(e) => onUpdatePage({ theme: e.target.value })}
            className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.82rem]"
          >
            {THEMES.map((t) => (
              <option key={t} value={t}>{t.toUpperCase()}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">{t("PANELS PER PAGE")}</label>
          <select
            value={page.panels.length}
            onChange={(e) => onReflowPages(Number(e.target.value))}
            className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.82rem]"
          >
            {PANELS_PER_PAGE.map((count) => (
              <option key={count} value={count}>{count} {count === 1 ? t("PANEL") : t("PANELS")} / {t("PAGE")}</option>
            ))}
          </select>
          <p className="mt-1 text-[0.72rem] leading-snug text-ink-black/45">
            {t("Reflows every panel and updates the page count.")}
          </p>
        </div>

        <div className="border-t-[2px] border-ink-black/10 pt-3">
          <div className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/45">
            {page.panels.length} {t("PANELS")} / {t("PAGE")} {String(page.page_number).padStart(2, "0")}
          </div>
        </div>

        <div className="border-t-[2px] border-ink-black/10 pt-3 space-y-2">
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

        <div className="border-t-[2px] border-ink-black/10 pt-3 space-y-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={onTranslateBubbles}
            disabled={isTranslatingBubbles}
            className="w-full"
          >
            {isTranslatingBubbles ? t("TRANSLATING...") : t("TRANSLATE EXISTING BUBBLES")}
          </Button>
          <p className="text-[0.72rem] leading-snug text-ink-black/45">
            {t("Translates assembled speech, thought, and narration text into the project output language.")}
          </p>
        </div>

        <div className="text-[0.78rem] text-ink-black/40">
          {t("Click a bubble or SFX on the page to edit its properties.")}
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
      <Card className="p-3 space-y-3">
        <div className="font-meta text-[0.65rem] tracking-[0.18em] text-ink-black/50">
          {t("BUBBLE")}
        </div>

        <div>
          <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">{t("TEXT")}</label>
          <EditableText
            value={bubble.text}
            onSave={(text) => onUpdateBubble(selection.panelId, bubble.id, { text })}
            multiline
            inputClassName="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.82rem] min-h-[60px]"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">{t("TYPE")}</label>
            <select
              value={bubble.type}
              onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { type: e.target.value as typeof bubble.type })}
              className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
            >
              {BUBBLE_TYPES.map((t) => (
                <option key={t} value={t}>{t.toUpperCase()}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">{t("SIDE")}</label>
            <select
              value={bubble.side}
              onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { side: e.target.value as typeof bubble.side })}
              className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
            >
              {SIDES.map((s) => (
                <option key={s} value={s}>{s.toUpperCase()}</option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">{t("WIDTH")}</label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={bubble.width ?? ""}
              placeholder="Auto"
              onChange={(e) => {
                const v = e.target.value ? Number(e.target.value) : null;
                onUpdateBubble(selection.panelId, bubble.id, { width: v });
              }}
              className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
            />
          </div>
        </div>

        <div className="border-t-[2px] border-ink-black/10 pt-3 space-y-3">
          <div className="font-meta text-[0.65rem] tracking-[0.18em] text-ink-black/50">
            {t("BUBBLE STYLE")}
          </div>

          <div>
            <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">FONT</label>
            <select
              value={bubble.font_family ?? ""}
              onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { font_family: e.target.value || null })}
              className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
            >
              <option value="">THEME DEFAULT</option>
              {FONT_OPTIONS.map((font) => (
                <option key={font.label} value={font.value}>{font.label.toUpperCase()}</option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">FONT SIZE</label>
              <input
                type="number"
                value={bubble.font_size ?? ""}
                placeholder="Auto"
                min={8}
                max={96}
                onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { font_size: e.target.value ? Number(e.target.value) : null })}
                className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
              />
            </div>
            <div>
              <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">BORDER PX</label>
              <input
                type="number"
                value={bubble.border_width ?? ""}
                placeholder="Auto"
                min={0}
                max={16}
                onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { border_width: e.target.value ? Number(e.target.value) : null })}
                className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">RADIUS</label>
              <input
                type="number"
                value={bubble.border_radius ?? ""}
                placeholder="Auto"
                min={0}
                max={120}
                onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { border_radius: e.target.value ? Number(e.target.value) : null })}
                className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
              />
            </div>
            <div>
              <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">TEXT</label>
              <input
                type="color"
                value={bubble.font_color ?? "#1A1A1A"}
                onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { font_color: e.target.value })}
                className="h-[36px] w-full border-[2px] border-ink-black bg-pulp-paper p-1"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">FILL</label>
              <input
                type="color"
                value={bubble.fill_color ?? "#FFFFFF"}
                onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { fill_color: e.target.value })}
                className="h-[36px] w-full border-[2px] border-ink-black bg-pulp-paper p-1"
              />
            </div>
            <div>
              <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">BORDER</label>
              <input
                type="color"
                value={bubble.border_color ?? "#1A1A1A"}
                onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { border_color: e.target.value })}
                className="h-[36px] w-full border-[2px] border-ink-black bg-pulp-paper p-1"
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

        <div className="border-t-[2px] border-ink-black/10 pt-3">
          <Button
            variant="outline"
            size="sm"
            onClick={() => onDeleteElement(selection.panelId, "bubble", bubble.id)}
          >
            DELETE BUBBLE
          </Button>
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
    <Card className="p-3 space-y-3">
      <div className="font-meta text-[0.65rem] tracking-[0.18em] text-ink-black/50">
        SFX
      </div>

      <div>
        <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">TEXT</label>
        <EditableText
          value={sfx.text}
          onSave={(text) => onUpdateSfx(selection.panelId, { text })}
          inputClassName="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.82rem]"
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">ROTATION</label>
          <input
            type="number"
            value={sfx.rotation}
            step={1}
            onChange={(e) => onUpdateSfx(selection.panelId, { rotation: Number(e.target.value) })}
            className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
          />
        </div>
        <div>
          <label className="font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/55 block mb-1">FONT SIZE</label>
          <input
            type="number"
            value={sfx.font_size ?? ""}
            placeholder="Auto"
            onChange={(e) => {
              const v = e.target.value ? Number(e.target.value) : null;
              onUpdateSfx(selection.panelId, { font_size: v });
            }}
            className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
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

      <div className="border-t-[2px] border-ink-black/10 pt-3">
        <Button
          variant="outline"
          size="sm"
          onClick={() => onDeleteElement(selection.panelId, "sfx", selection.elementId)}
        >
          DELETE SFX
        </Button>
      </div>
    </Card>
  );
}

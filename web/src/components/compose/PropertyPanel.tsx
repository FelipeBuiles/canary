import { Card } from "../ui/Card";
import { Button } from "../ui/Button";
import type { ComicPage, Bubble, Sfx, PagePanel } from "../../types/api";
import { EditableText } from "../ui/EditableText";

interface PropertyPanelProps {
  page: ComicPage;
  selection: { panelId: string; type: "bubble" | "sfx"; elementId: string } | null;
  onUpdateBubble: (panelId: string, bubbleId: string, patch: Partial<Bubble>) => void;
  onUpdateSfx: (panelId: string, patch: Partial<Sfx>) => void;
  onUpdatePage: (patch: Partial<ComicPage>) => void;
  onDeleteElement: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
  onUnpin: (panelId: string, type: "bubble" | "sfx", elementId: string) => void;
}

const THEMES = ["default", "noir", "manga", "vintage", "painted"];
const LAYOUTS = ["1", "2", "3", "4", "5", "6", "many"];
const BUBBLE_TYPES = ["speech", "thought", "narration"] as const;
const SIDES = ["left", "right", "center"] as const;

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
  onDeleteElement,
  onUnpin,
}: PropertyPanelProps) {
  if (!selection) {
    return (
      <Card className="p-4 space-y-4">
        <div className="font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
          PAGE PROPERTIES
        </div>

        <div>
          <label className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/50 block mb-1">THEME</label>
          <select
            value={page.theme}
            onChange={(e) => onUpdatePage({ theme: e.target.value })}
            className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
          >
            {THEMES.map((t) => (
              <option key={t} value={t}>{t.toUpperCase()}</option>
            ))}
          </select>
        </div>

        <div>
          <label className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/50 block mb-1">LAYOUT</label>
          <select
            value={page.layout}
            onChange={(e) => onUpdatePage({ layout: e.target.value })}
            className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
          >
            {LAYOUTS.map((l) => (
              <option key={l} value={l}>{l === "many" ? "MANY (>6)" : `${l} PANEL${l === "1" ? "" : "S"}`}</option>
            ))}
          </select>
        </div>

        <div className="border-t-[2px] border-ink-black/10 pt-3">
          <div className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/40">
            {page.panels.length} PANELS / PAGE {String(page.page_number).padStart(2, "0")}
          </div>
        </div>

        <div className="text-[0.72rem] text-ink-black/40">
          Click a bubble or SFX on the page to edit its properties.
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
      <Card className="p-4 space-y-3">
        <div className="font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
          BUBBLE
        </div>

        <div>
          <label className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/50 block mb-1">TEXT</label>
          <EditableText
            value={bubble.text}
            onSave={(text) => onUpdateBubble(selection.panelId, bubble.id, { text })}
            multiline
            inputClassName="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem] min-h-[60px]"
          />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <div>
            <label className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/50 block mb-1">TYPE</label>
            <select
              value={bubble.type}
              onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { type: e.target.value as typeof bubble.type })}
              className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.72rem]"
            >
              {BUBBLE_TYPES.map((t) => (
                <option key={t} value={t}>{t.toUpperCase()}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/50 block mb-1">SIDE</label>
            <select
              value={bubble.side}
              onChange={(e) => onUpdateBubble(selection.panelId, bubble.id, { side: e.target.value as typeof bubble.side })}
              className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.72rem]"
            >
              {SIDES.map((s) => (
                <option key={s} value={s}>{s.toUpperCase()}</option>
              ))}
            </select>
          </div>
        </div>

        <div>
          <label className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/50 block mb-1">WIDTH</label>
          <div className="flex items-center gap-2">
            <input
              type="number"
              value={bubble.width ?? ""}
              placeholder="Auto"
              onChange={(e) => {
                const v = e.target.value ? Number(e.target.value) : null;
                onUpdateBubble(selection.panelId, bubble.id, { width: v });
              }}
              className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.72rem]"
            />
          </div>
        </div>

        {isPinned && (
          <div className="space-y-1">
            <div className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/40">
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
    <Card className="p-4 space-y-3">
      <div className="font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/45">
        SFX
      </div>

      <div>
        <label className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/50 block mb-1">TEXT</label>
        <EditableText
          value={sfx.text}
          onSave={(text) => onUpdateSfx(selection.panelId, { text })}
          inputClassName="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.78rem]"
        />
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/50 block mb-1">ROTATION</label>
          <input
            type="number"
            value={sfx.rotation}
            step={1}
            onChange={(e) => onUpdateSfx(selection.panelId, { rotation: Number(e.target.value) })}
            className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.72rem]"
          />
        </div>
        <div>
          <label className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/50 block mb-1">FONT SIZE</label>
          <input
            type="number"
            value={sfx.font_size ?? ""}
            placeholder="Auto"
            onChange={(e) => {
              const v = e.target.value ? Number(e.target.value) : null;
              onUpdateSfx(selection.panelId, { font_size: v });
            }}
            className="w-full border-[2px] border-ink-black bg-pulp-paper px-2 py-1.5 font-body text-[0.72rem]"
          />
        </div>
      </div>

      {sfxPinned && (
        <div className="space-y-1">
          <div className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/40">
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

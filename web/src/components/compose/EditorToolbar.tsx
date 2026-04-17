import { Button } from "../ui/Button";

interface EditorToolbarProps {
  onAddBubble: (type: "speech" | "thought" | "narration") => void;
  onAddSfx: () => void;
  onDelete: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onExport: (format: "pdf" | "cbz") => void;
  hasSelection: boolean;
  canUndo: boolean;
  canRedo: boolean;
  isExporting: boolean;
}

export function EditorToolbar({
  onAddBubble,
  onAddSfx,
  onDelete,
  onUndo,
  onRedo,
  onExport,
  hasSelection,
  canUndo,
  canRedo,
  isExporting,
}: EditorToolbarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 border-[2px] border-ink-black bg-bristol px-3 py-2">
      <div className="flex items-center gap-1.5">
        <Button size="xs" variant="secondary" onClick={() => onAddBubble("speech")}>
          + SPEECH
        </Button>
        <Button size="xs" variant="secondary" onClick={() => onAddBubble("thought")}>
          + THOUGHT
        </Button>
        <Button size="xs" variant="secondary" onClick={() => onAddBubble("narration")}>
          + NARRATION
        </Button>
        <Button size="xs" variant="secondary" onClick={onAddSfx}>
          + SFX
        </Button>
      </div>

      <div className="mx-1 h-4 w-px bg-ink-black/20" />

      <Button size="xs" variant="outline" onClick={onDelete} disabled={!hasSelection}>
        DELETE
      </Button>

      <div className="mx-1 h-4 w-px bg-ink-black/20" />

      <Button size="xs" variant="outline" onClick={onUndo} disabled={!canUndo}>
        UNDO
      </Button>
      <Button size="xs" variant="outline" onClick={onRedo} disabled={!canRedo}>
        REDO
      </Button>

      <div className="ml-auto flex items-center gap-1.5">
        <Button
          size="xs"
          variant="primary"
          onClick={() => onExport("pdf")}
          disabled={isExporting}
        >
          {isExporting ? "EXPORTING..." : "EXPORT PDF"}
        </Button>
        <Button
          size="xs"
          variant="secondary"
          onClick={() => onExport("cbz")}
          disabled={isExporting}
        >
          CBZ
        </Button>
      </div>
    </div>
  );
}

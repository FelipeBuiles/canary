import type { ReactNode } from "react";
import { Icon } from "../ui/Icon";
import { ShortcutHint } from "../ui/ShortcutHint";
import { cn } from "../../lib/cn";

interface EditorToolbarProps {
  onAddBubble: (type: "speech" | "thought" | "narration") => void;
  onAddSfx: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
}

interface ToolbarButtonProps {
  label: string;
  shortcut?: string;
  icon?: ReactNode;
  onClick: () => void;
  disabled?: boolean;
}

function ToolbarButton({
  label,
  shortcut,
  icon,
  onClick,
  disabled = false,
}: ToolbarButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex min-h-11 items-center gap-2 border border-ink-black/22 bg-pulp-paper px-2.5 font-meta text-[0.52rem] tracking-[0.14em] text-ink-black transition-colors hover:bg-bristol disabled:cursor-not-allowed disabled:opacity-35",
      )}
    >
      {icon}
      <span>{label}</span>
      {shortcut && <ShortcutHint>{shortcut}</ShortcutHint>}
    </button>
  );
}

export function EditorToolbar({
  onAddBubble,
  onAddSfx,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
}: EditorToolbarProps) {
  return (
    <div className="flex min-h-10 flex-wrap items-center gap-x-5 gap-y-2 bg-pulp-paper px-3 py-2">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-meta text-[0.52rem] tracking-[0.16em] text-ink-black/45">ADD:</span>
        <ToolbarButton label="SPEECH" shortcut="B" icon={<Icon name="speech" size={12} />} onClick={() => onAddBubble("speech")} />
        <ToolbarButton label="THOUGHT" shortcut="T" icon={<Icon name="thought" size={12} />} onClick={() => onAddBubble("thought")} />
        <ToolbarButton label="NARRATION" shortcut="N" icon={<Icon name="type" size={12} />} onClick={() => onAddBubble("narration")} />
        <ToolbarButton label="SFX" shortcut="X" icon={<Icon name="sparkles" size={12} />} onClick={onAddSfx} />
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <ToolbarButton label="UNDO" shortcut="⌘Z" icon={<Icon name="undo" size={12} />} onClick={onUndo} disabled={!canUndo} />
        <ToolbarButton label="REDO" shortcut="⇧⌘Z" icon={<Icon name="redo" size={12} />} onClick={onRedo} disabled={!canRedo} />
      </div>
    </div>
  );
}

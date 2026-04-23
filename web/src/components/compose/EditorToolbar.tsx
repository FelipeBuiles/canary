import { Icon } from "../ui/Icon";
import { cn } from "../../lib/cn";

interface EditorToolbarProps {
  onAddBubble: (type: "speech" | "thought" | "narration") => void;
  onAddSfx: () => void;
  onDelete: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onTryLayouts: () => void;
  onSelectNarration: () => void;
  onSelectBySpeaker: () => void;
  hasSelection: boolean;
  canUndo: boolean;
  canRedo: boolean;
  zoomPercent: number;
  selectedSpeakerLabel?: string | null;
  panelCount: number;
  bubbleCount: number;
  sfxCount: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onZoomReset: () => void;
}

export function EditorToolbar({
  onAddBubble,
  onAddSfx,
  onDelete,
  onUndo,
  onRedo,
  onTryLayouts,
  onSelectNarration,
  onSelectBySpeaker,
  hasSelection,
  canUndo,
  canRedo,
  zoomPercent,
  selectedSpeakerLabel,
  panelCount,
  bubbleCount,
  sfxCount,
  onZoomIn,
  onZoomOut,
  onZoomReset,
}: EditorToolbarProps) {
  function ToolbarButton({
    label,
    shortcut,
    icon,
    onClick,
    disabled = false,
    emphasized = false,
  }: {
    label: string;
    shortcut?: string;
    icon?: React.ReactNode;
    onClick: () => void;
    disabled?: boolean;
    emphasized?: boolean;
  }) {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        className={cn(
          "inline-flex h-8 items-center gap-2 border border-ink-black/20 bg-pulp-paper px-2.5 font-meta text-[0.56rem] tracking-[0.12em] text-ink-black transition-colors hover:bg-bristol disabled:cursor-not-allowed disabled:opacity-35",
          emphasized && "border-ink-black/35 bg-bristol",
        )}
      >
        {icon}
        <span>{label}</span>
        {shortcut && (
          <span className="ml-1 inline-flex h-4 min-w-4 items-center justify-center border border-ink-black/15 px-1 text-[0.44rem] text-ink-black/45">
            {shortcut}
          </span>
        )}
      </button>
    );
  }

  return (
    <div className="flex min-h-10 flex-wrap items-center gap-x-3 gap-y-2 border-y border-ink-black/20 bg-pulp-paper px-3 py-2">
      <div className="flex items-center gap-1.5">
        <span className="font-meta text-[0.52rem] tracking-[0.16em] text-ink-black/45">ADD:</span>
        <ToolbarButton label="SPEECH" shortcut="B" icon={<Icon name="speech" size={12} />} onClick={() => onAddBubble("speech")} />
        <ToolbarButton label="THOUGHT" shortcut="T" icon={<Icon name="thought" size={12} />} onClick={() => onAddBubble("thought")} />
        <ToolbarButton label="NARRATION" shortcut="N" icon={<Icon name="type" size={12} />} onClick={() => onAddBubble("narration")} />
        <ToolbarButton label="SFX" shortcut="X" icon={<Icon name="sparkles" size={12} />} onClick={onAddSfx} />
      </div>

      <div className="flex items-center gap-1.5">
        <span className="font-meta text-[0.52rem] tracking-[0.16em] text-ink-black/45">BULK:</span>
        <ToolbarButton label="ALL NARRATION" onClick={onSelectNarration} />
        <ToolbarButton
          label={selectedSpeakerLabel ? `ALL BY ${selectedSpeakerLabel.toUpperCase()}` : "ALL BY SPEAKER"}
          onClick={onSelectBySpeaker}
          disabled={!selectedSpeakerLabel}
        />
      </div>

      <div className="ml-auto flex items-center gap-1.5">
        <ToolbarButton label="DELETE" icon={<Icon name="trash" size={12} />} onClick={onDelete} disabled={!hasSelection} />
        <ToolbarButton label="UNDO" icon={<Icon name="undo" size={12} />} onClick={onUndo} disabled={!canUndo} />
        <ToolbarButton label="REDO" icon={<Icon name="redo" size={12} />} onClick={onRedo} disabled={!canRedo} />
        <ToolbarButton label="TRY LAYOUTS" shortcut="⌘L" icon={<Icon name="assets" size={12} />} onClick={onTryLayouts} emphasized />
        <div className="flex items-center gap-1">
          <ToolbarButton label="" icon={<Icon name="zoom-out" size={12} />} onClick={onZoomOut} />
          <button
            type="button"
            onClick={onZoomReset}
            className="inline-flex h-8 min-w-[54px] items-center justify-center border border-ink-black/20 bg-bristol px-2 font-meta text-[0.56rem] tracking-[0.12em] text-ink-black"
          >
            {Math.round(zoomPercent)}%
          </button>
          <ToolbarButton label="" icon={<Icon name="zoom-in" size={12} />} onClick={onZoomIn} />
        </div>
        <div className="hidden items-center gap-2 pl-3 font-meta text-[0.52rem] tracking-[0.16em] text-ink-black/38 xl:flex">
          <span>{panelCount} PANELS</span>
          <span>·</span>
          <span>{bubbleCount} BUBBLES</span>
          <span>·</span>
          <span>{sfxCount} SFX</span>
        </div>
      </div>
    </div>
  );
}

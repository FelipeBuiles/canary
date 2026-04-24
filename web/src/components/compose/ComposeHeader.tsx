import type { ComposeMode } from "./compose-types";
import { Icon } from "../ui/Icon";

interface ComposeHeaderProps {
  mode: ComposeMode;
  isExporting: boolean;
  onExport: (format: "pdf" | "cbz") => void;
  onOpenCmdk: () => void;
  onPreview: () => void;
  rerunAction?: React.ReactNode;
}

export function ComposeHeader({
  mode,
  isExporting,
  onExport,
  onOpenCmdk,
  onPreview,
  rerunAction,
}: ComposeHeaderProps) {
  function UtilityButton({
    label,
    shortcut,
    onClick,
    icon,
    emphasized = false,
  }: {
    label: string;
    shortcut?: string;
    onClick: () => void;
    icon?: React.ReactNode;
    emphasized?: boolean;
  }) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex h-8 items-center gap-2 border px-3 font-meta text-[0.52rem] tracking-[0.16em] transition-colors ${
          emphasized
            ? "border-[#9e4734] bg-[#a84a35] text-bristol hover:bg-[#943c28]"
            : "border-ink-black/20 bg-bristol text-ink-black hover:bg-surface-container"
        }`}
      >
        {icon}
        <span>{label}</span>
        {shortcut ? (
          <span className={`inline-flex h-4 min-w-4 items-center justify-center rounded-[2px] border px-1 text-[0.42rem] ${
            emphasized ? "border-bristol/30 text-bristol/70" : "border-ink-black/15 text-ink-black/45"
          }`}>
            {shortcut}
          </span>
        ) : null}
      </button>
    );
  }

  return (
    <section className="m-2 shrink-0 border-[3px] border-ink-black bg-bristol px-5 py-4 shadow-[3px_3px_0_0_var(--color-ink-black)] md:px-7 md:py-4.5">
      <div className="flex items-start justify-between gap-6">
        <span className="inline-flex min-h-7 items-center bg-hero-red px-3 py-1 font-meta text-[0.5rem] tracking-[0.22em] uppercase text-bristol">
          COMPOSE · {mode.toUpperCase()}
        </span>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {rerunAction}
          <UtilityButton label="COMMANDS" shortcut="⌘K" icon={<Icon name="search" size={12} />} onClick={onOpenCmdk} />
          <UtilityButton label="PREVIEW" icon={<Icon name="eye" size={12} />} onClick={onPreview} />
          <UtilityButton
            label={isExporting ? "EXPORTING…" : "EXPORT PDF"}
            shortcut="⌘E"
            icon={<Icon name="export" size={12} />}
            onClick={() => onExport("pdf")}
            emphasized
          />
        </div>
      </div>
      <h1 className="mt-2 font-display text-[clamp(2.5rem,4.1vw,4rem)] font-black uppercase leading-none tracking-[-0.06em] text-ink-black [font-stretch:75%]">
        COMPOSE.
      </h1>
      <div className="mt-1.5 flex items-center gap-2 border-l-[3px] border-hero-red pl-3 text-[0.86rem] text-ink-black/56">
        <span>Four modes, not one canvas.</span>
        <span className="hidden text-ink-black/30 md:inline">Switch with</span>
        <span className="hidden items-center gap-1 md:inline-flex">
          <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-ink-black/15 bg-bristol px-1 text-[0.58rem] text-ink-black/46">1</kbd>
          <kbd className="inline-flex h-5 min-w-5 items-center justify-center rounded border border-ink-black/15 bg-bristol px-1 text-[0.58rem] text-ink-black/46">4</kbd>
        </span>
        <span className="hidden text-ink-black/30 md:inline">Run anything with</span>
        <kbd className="hidden h-5 min-w-5 items-center justify-center rounded border border-ink-black/15 bg-bristol px-1 text-[0.58rem] text-ink-black/46 md:inline-flex">⌘K</kbd>
      </div>
    </section>
  );
}

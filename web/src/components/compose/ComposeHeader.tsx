import type { ComposeMode } from "./compose-types";

interface ComposeHeaderProps {
  mode: ComposeMode;
  isExporting: boolean;
  onExport: (format: "pdf" | "cbz") => void;
  onOpenCmdk: () => void;
  onPreview: () => void;
}

export function ComposeHeader({
  mode,
  isExporting,
  onExport,
  onOpenCmdk,
  onPreview,
}: ComposeHeaderProps) {
  function UtilityButton({
    label,
    shortcut,
    onClick,
    emphasized = false,
  }: {
    label: string;
    shortcut?: string;
    onClick: () => void;
    emphasized?: boolean;
  }) {
    return (
      <button
        type="button"
        onClick={onClick}
        className={`inline-flex h-9 items-center gap-2 border px-3.5 font-meta text-[0.58rem] tracking-[0.14em] transition-colors ${
          emphasized
            ? "border-[#9e4734] bg-[#a84a35] text-bristol hover:bg-[#943c28]"
            : "border-ink-black/20 bg-bristol text-ink-black hover:bg-surface-container"
        }`}
      >
        <span>{label}</span>
        {shortcut ? (
          <span className={`inline-flex h-4 min-w-4 items-center justify-center border px-1 text-[0.42rem] ${
            emphasized ? "border-bristol/30 text-bristol/70" : "border-ink-black/15 text-ink-black/45"
          }`}>
            {shortcut}
          </span>
        ) : null}
      </button>
    );
  }

  return (
    <section className="shrink-0 border-b-[2px] border-ink-black bg-bristol px-7 py-4 md:px-8 md:py-4.5">
      <div className="flex items-start justify-between gap-6">
        <span className="inline-flex min-h-7 items-center bg-hero-red px-3 py-1 font-meta text-[0.5rem] tracking-[0.22em] uppercase text-bristol">
          COMPOSE · {mode.toUpperCase()}
        </span>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <UtilityButton label="COMMANDS" shortcut="⌘K" onClick={onOpenCmdk} />
          <UtilityButton label="PREVIEW" onClick={onPreview} />
          <UtilityButton
            label={isExporting ? "EXPORTING…" : "EXPORT PDF"}
            shortcut="⌘E"
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

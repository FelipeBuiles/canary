import { cn } from "../../lib/cn";
import type { ComposeTab } from "./compose-types";

const TABS: { id: ComposeTab; label: string }[] = [
  { id: "edit", label: "EDIT" },
  { id: "export", label: "EXPORT" },
];

interface ComposeHeaderProps {
  tab: ComposeTab;
  onTabChange: (tab: ComposeTab) => void;
  isExporting: boolean;
  isMatchingStyle: boolean;
  onExport: (format: "pdf" | "cbz") => void;
  onMatchStyle: () => void;
  rerunAction?: React.ReactNode;
  pageCount?: number;
}

export function ComposeHeader({
  tab,
  onTabChange,
  isExporting,
  isMatchingStyle,
  onExport,
  onMatchStyle,
  rerunAction,
  pageCount,
}: ComposeHeaderProps) {
  return (
    <header className="flex h-14 shrink-0 items-stretch border-b-[2px] border-ink-black bg-bristol">
      {/* Identity */}
      <div className="flex shrink-0 items-center gap-0 px-5">
        <span className="bg-hero-red px-3 py-1 font-meta text-[0.56rem] tracking-[0.22em] uppercase text-bristol">
          COMPOSE
        </span>
        <span className="mx-4 h-4 w-px shrink-0 bg-ink-black/20" />
        <span className="font-display text-[1.12rem] font-black uppercase leading-none tracking-[-0.03em] text-ink-black [font-stretch:75%]">
          COMIC PAGES
        </span>
      </div>

      {/* Tab strip */}
      <div className="flex flex-1 items-stretch border-l-[2px] border-ink-black/10">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            onClick={() => onTabChange(t.id)}
            className={cn(
              "flex items-center px-5 font-meta text-[0.56rem] tracking-[0.2em] transition-colors",
              t.id === tab
                ? "bg-ink-black text-bristol"
                : "text-ink-black/38 hover:text-ink-black/70",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Actions */}
      <div className="flex shrink-0 items-center gap-2 px-3">
        {pageCount != null && (
          <span className="font-meta text-[0.48rem] tracking-[0.14em] text-ink-black/35">
            {pageCount}P
          </span>
        )}
        {rerunAction}
        <button
          type="button"
          onClick={onMatchStyle}
          disabled={isMatchingStyle}
          className="flex h-8 items-center gap-1.5 bg-hero-red px-4 font-meta text-[0.5rem] tracking-[0.18em] text-bristol transition-opacity hover:opacity-90 disabled:opacity-60"
        >
          ♦ {isMatchingStyle ? "MATCHING…" : "MATCH LETTERING"}
        </button>
        <button
          type="button"
          onClick={() => onExport("pdf")}
          disabled={isExporting}
          className="flex h-8 items-center border-[1.5px] border-ink-black px-3 font-meta text-[0.5rem] tracking-[0.16em] text-ink-black transition-opacity hover:opacity-70 disabled:opacity-50"
        >
          {isExporting ? "EXPORTING…" : "PDF"}
        </button>
        <button
          type="button"
          onClick={() => onExport("cbz")}
          disabled={isExporting}
          className="flex h-8 items-center border-[1.5px] border-ink-black/30 px-3 font-meta text-[0.5rem] tracking-[0.16em] text-ink-black/50 transition-colors hover:border-ink-black/60 hover:text-ink-black/70 disabled:opacity-50"
        >
          CBZ
        </button>
      </div>
    </header>
  );
}

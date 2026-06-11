import { useEffect, useRef, useState } from "react";
import { cn } from "../../lib/cn";
import type { ComposeTab } from "./compose-types";

const TABS: { id: ComposeTab; label: string }[] = [
  { id: "pages", label: "PAGES" },
  { id: "script", label: "SCRIPT" },
  { id: "export", label: "EXPORT" },
];

interface ComposeHeaderProps {
  tab: ComposeTab;
  onTabChange: (tab: ComposeTab) => void;
  errorCount: number;
  warningCount: number;
  onOpenIssues: () => void;
  isMatchingStyle: boolean;
  onMatchStyle: () => void;
  rerunAction?: React.ReactNode;
  pageCount?: number;
}

/** ⟳ Regenerate ▾ — the one home for whole-book regeneration verbs. */
function RegenerateMenu({
  rerunAction,
  isMatchingStyle,
  onMatchStyle,
}: {
  rerunAction?: React.ReactNode;
  isMatchingStyle: boolean;
  onMatchStyle: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex h-8 items-center gap-1.5 border-[1.5px] border-ink-black/30 px-3 font-meta text-[0.5rem] tracking-[0.16em] text-ink-black/60 transition-colors hover:border-ink-black hover:text-ink-black"
      >
        ⟳ REGENERATE ▾
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 flex w-56 flex-col gap-2 border-[2px] border-ink-black bg-bristol p-3 shadow-ink-sm">
          <button
            type="button"
            onClick={() => { setOpen(false); onMatchStyle(); }}
            disabled={isMatchingStyle}
            className="flex h-8 items-center justify-center gap-1.5 bg-hero-red px-4 font-meta text-[0.5rem] tracking-[0.18em] text-bristol transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            ♦ {isMatchingStyle ? "MATCHING…" : "MATCH LETTERING"}
          </button>
          {rerunAction}
        </div>
      )}
    </div>
  );
}

export function ComposeHeader({
  tab,
  onTabChange,
  errorCount,
  warningCount,
  onOpenIssues,
  isMatchingStyle,
  onMatchStyle,
  rerunAction,
  pageCount,
}: ComposeHeaderProps) {
  const issueChipLabel = [
    errorCount > 0 ? `${errorCount} NEED YOU` : null,
    warningCount > 0 ? `${warningCount} SUGGESTION${warningCount === 1 ? "" : "S"}` : null,
  ].filter(Boolean).join(" · ");

  return (
    <header className="flex h-14 shrink-0 items-stretch border-b-[2px] border-ink-black bg-bristol">
      {/* Identity */}
      <div className="flex shrink-0 items-center gap-0 px-5">
        <span className="bg-hero-red px-3 py-1 font-meta text-[0.56rem] tracking-[0.22em] uppercase text-bristol">
          BOOK
        </span>
        <span className="mx-4 h-4 w-px shrink-0 bg-ink-black/20" />
        <span className="font-display text-[1.12rem] font-black uppercase leading-none tracking-[-0.03em] text-ink-black [font-stretch:75%]">
          COMIC PAGES
        </span>
      </div>

      {/* The only tab row */}
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
        {issueChipLabel && (
          <button
            type="button"
            onClick={onOpenIssues}
            className={cn(
              "flex h-8 items-center gap-1.5 border-[1.5px] px-3 font-meta text-[0.5rem] tracking-[0.14em] transition-colors",
              errorCount > 0
                ? "border-hero-red text-hero-red hover:bg-hero-red hover:text-bristol"
                : "border-ink-black/30 text-ink-black/60 hover:border-ink-black hover:text-ink-black",
            )}
          >
            ⚑ {issueChipLabel}
          </button>
        )}
        <RegenerateMenu
          rerunAction={rerunAction}
          isMatchingStyle={isMatchingStyle}
          onMatchStyle={onMatchStyle}
        />
      </div>
    </header>
  );
}

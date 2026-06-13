import { useEffect, useRef, useState } from "react";
import { cn } from "../../lib/cn";
import { TopBarPortal } from "../../layout/TopBarSlot";
import type { ComposeTab } from "./compose-types";

const TABS: { id: ComposeTab; label: string }[] = [
  { id: "pages", label: "PAGES" },
  { id: "script", label: "SCRIPT" },
  { id: "export", label: "EXPORT" },
];

const LETTERING_PRESETS: { id: string; label: string }[] = [
  { id: "default", label: "DEFAULT" },
  { id: "noir", label: "NOIR" },
  { id: "manga", label: "MANGA" },
  { id: "vintage", label: "VINTAGE" },
  { id: "painted", label: "PAINTED" },
];

interface ComposeHeaderProps {
  tab: ComposeTab;
  onTabChange: (tab: ComposeTab) => void;
  errorCount: number;
  warningCount: number;
  onOpenIssues: () => void;
  letteringLabel?: string;
  isLettering: boolean;
  onRerollLettering: () => void;
  onSetLetteringPreset: (preset: string) => void;
  onEditLetteringAtLook: () => void;
  rerunAction?: React.ReactNode;
  pageCount?: number;
}

function useDismissOnOutside(open: boolean, onClose: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    function onPointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) onClose();
    }
    window.addEventListener("pointerdown", onPointerDown);
    return () => window.removeEventListener("pointerdown", onPointerDown);
  }, [open, onClose]);
  return ref;
}

/** ✦ Lettering ▾ — the named, visible home for whole-book lettering tweaks. */
function LetteringMenu({
  label,
  isLettering,
  onReroll,
  onSetPreset,
  onEditAtLook,
}: {
  label?: string;
  isLettering: boolean;
  onReroll: () => void;
  onSetPreset: (preset: string) => void;
  onEditAtLook: () => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useDismissOnOutside(open, () => setOpen(false));

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex h-8 max-w-[11rem] items-center gap-1.5 border-[1.5px] border-ink-black/30 px-3 font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/60 transition-colors hover:border-ink-black hover:text-ink-black"
      >
        <span className="truncate">✦ {isLettering ? "MATCHING…" : label || "LETTERING"}</span>
        <span aria-hidden>▾</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 flex w-60 flex-col gap-2 border-[2px] border-ink-black bg-bristol p-3 shadow-ink-sm">
          <button
            type="button"
            onClick={() => { setOpen(false); onReroll(); }}
            disabled={isLettering}
            className="flex h-8 items-center justify-center gap-1.5 bg-hero-red px-4 font-meta text-[0.5rem] tracking-[0.18em] text-bristol transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            ↺ {isLettering ? "MATCHING…" : "ANOTHER TAKE"}
          </button>
          <div className="mt-1 font-meta text-[0.46rem] tracking-[0.16em] text-ink-black/40">OR PICK A PRESET</div>
          <div className="flex flex-wrap gap-1.5">
            {LETTERING_PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => { setOpen(false); onSetPreset(p.id); }}
                disabled={isLettering}
                className="border-[2px] border-ink-black bg-bristol px-2 py-1 font-meta text-[0.48rem] tracking-[0.1em] transition-colors hover:bg-surface-container disabled:opacity-50"
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => { setOpen(false); onEditAtLook(); }}
            className="mt-1 border-t border-ink-black/10 pt-2 text-left font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/55 transition-colors hover:text-ink-black"
          >
            EDIT AT LOOK →
          </button>
          <p className="font-meta text-[0.44rem] leading-4 tracking-[0.08em] text-ink-black/35">
            PER-BUBBLE TWEAKS STAY PUT WHEN YOU CHANGE THE BOOK&apos;S LETTERING.
          </p>
        </div>
      )}
    </div>
  );
}

/** ⟳ Regenerate ▾ — whole-book compose re-run. */
function RegenerateMenu({ rerunAction }: { rerunAction?: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useDismissOnOutside(open, () => setOpen(false));
  if (!rerunAction) return null;

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
  letteringLabel,
  isLettering,
  onRerollLettering,
  onSetLetteringPreset,
  onEditLetteringAtLook,
  rerunAction,
  pageCount,
}: ComposeHeaderProps) {
  const issueChipLabel = [
    errorCount > 0 ? `${errorCount} NEED YOU` : null,
    warningCount > 0 ? `${warningCount} SUGGESTION${warningCount === 1 ? "" : "S"}` : null,
  ].filter(Boolean).join(" · ");

  const tabRow = (
    <div className="flex min-w-0 flex-1 items-stretch border-l-[2px] border-ink-black/10">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          onClick={() => onTabChange(t.id)}
          className={cn(
            "flex shrink-0 items-center px-5 font-meta text-[0.56rem] tracking-[0.2em] transition-colors",
            t.id === tab
              ? "bg-ink-black text-bristol"
              : "text-ink-black/38 hover:text-ink-black/70",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );

  const actions = (
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
      <LetteringMenu
        label={letteringLabel}
        isLettering={isLettering}
        onReroll={onRerollLettering}
        onSetPreset={onSetLetteringPreset}
        onEditAtLook={onEditLetteringAtLook}
      />
      <RegenerateMenu rerunAction={rerunAction} />
    </div>
  );

  // Identity + (on md+) tabs and actions live in the shell masthead; on
  // mobile the tabs/actions drop to their own in-flow bar below it.
  return (
    <>
      <TopBarPortal>
        <div className="flex shrink-0 flex-col items-start justify-center gap-1.5 px-5">
          <span className="bg-hero-red px-2.5 py-[3px] font-meta text-[0.5rem] tracking-[0.22em] uppercase text-bristol">
            BOOK
          </span>
          <h1 className="font-display text-[1.55rem] font-black uppercase leading-[0.85] tracking-[-0.04em] text-ink-black [font-stretch:75%]">
            COMIC PAGES
          </h1>
        </div>
        <div className="hidden min-w-0 flex-1 items-stretch md:flex">
          {tabRow}
          {actions}
        </div>
      </TopBarPortal>

      <div className="flex min-h-12 shrink-0 flex-wrap items-stretch border-b-[2px] border-ink-black bg-bristol md:hidden">
        <div className="flex h-12 min-w-[13rem] flex-1 items-stretch">{tabRow}</div>
        <div className="ml-auto flex h-12 items-center">{actions}</div>
      </div>
    </>
  );
}

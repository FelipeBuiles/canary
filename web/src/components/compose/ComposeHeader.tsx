import { useEffect, useRef, useState } from "react";
import { cn } from "../../lib/cn";
import { TopBarPortal } from "../../layout/TopBarSlot";
import { ShortcutHint } from "../ui/ShortcutHint";
import type { ComposeTab } from "./compose-types";

const TABS: { id: ComposeTab; label: string; shortcut: string }[] = [
  { id: "pages", label: "PAGES", shortcut: "1" },
  { id: "script", label: "TEXT", shortcut: "2" },
  { id: "export", label: "DOWNLOAD", shortcut: "3" },
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
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("pointerdown", onPointerDown);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointerdown", onPointerDown);
      window.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose]);
  return ref;
}

/** The named, visible home for whole-book lettering tweaks. */
function LetteringMenu({
  label,
  isLettering,
  onReroll,
  onSetPreset,
  onEditAtLook,
  rerunAction,
}: {
  label?: string;
  isLettering: boolean;
  onReroll: () => void;
  onSetPreset: (preset: string) => void;
  onEditAtLook: () => void;
  rerunAction?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const ref = useDismissOnOutside(open, () => setOpen(false));

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex min-h-11 max-w-[12rem] items-center gap-1.5 border-[2px] border-ink-black/25 px-3 font-meta text-[0.56rem] font-bold tracking-[0.08em] text-ink-muted transition-colors hover:border-ink-black hover:text-ink-black"
      >
        <span className="truncate">{isLettering ? "MATCHING…" : "BOOK OPTIONS"}</span>
        <span aria-hidden>▾</span>
      </button>
      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 flex w-60 flex-col gap-2 border-[2px] border-ink-black bg-bristol p-3 shadow-ink-sm">
          <div className="font-meta text-[0.54rem] font-bold tracking-[0.08em] text-ink-muted">
            LETTERING · {label || "DEFAULT"}
          </div>
          <button
            type="button"
            onClick={() => { setOpen(false); onReroll(); }}
            disabled={isLettering}
            className="flex min-h-11 items-center justify-center gap-1.5 border-[2px] border-ink-black bg-hero-red px-4 font-meta text-[0.56rem] font-bold tracking-[0.08em] text-bristol shadow-paper-sm transition-[box-shadow,transform] hover:translate-x-px hover:translate-y-px active:translate-x-[3px] active:translate-y-[3px] active:shadow-none disabled:opacity-60"
          >
            ↺ {isLettering ? "MATCHING…" : "ANOTHER TAKE"}
          </button>
          <div className="mt-1 font-meta text-[0.54rem] font-bold tracking-[0.08em] text-ink-muted">OR PICK A PRESET</div>
          <div className="flex flex-wrap gap-1.5">
            {LETTERING_PRESETS.map((p) => (
              <button
                key={p.id}
                type="button"
                onClick={() => { setOpen(false); onSetPreset(p.id); }}
                disabled={isLettering}
                className="min-h-9 border-[2px] border-ink-black bg-bristol px-2 py-1 font-meta text-[0.54rem] font-bold tracking-[0.06em] transition-colors hover:bg-surface-container disabled:opacity-50"
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => { setOpen(false); onEditAtLook(); }}
            className="mt-1 border-t-[2px] border-ink-black/10 pt-3 text-left font-meta text-[0.56rem] font-bold tracking-[0.08em] text-ink-muted transition-colors hover:text-ink-black"
          >
            EDIT AT LOOK →
          </button>
          <p className="font-body text-[0.68rem] font-semibold leading-4 text-ink-muted">
            PER-BUBBLE TWEAKS STAY PUT WHEN YOU CHANGE THE BOOK&apos;S LETTERING.
          </p>
          {rerunAction && (
            <div className="mt-1 border-t-[2px] border-ink-black/10 pt-3">
              <div className="mb-2 font-meta text-[0.54rem] font-bold tracking-[0.08em] text-ink-muted">REBUILD BOOK</div>
              {rerunAction}
            </div>
          )}
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
    <div className="flex min-w-0 flex-1 items-stretch border-x-[2px] border-ink-black/10" role="tablist" aria-label="Book workspace">
      {TABS.map((t) => (
        <button
          key={t.id}
          type="button"
          role="tab"
          aria-selected={t.id === tab}
          onClick={() => onTabChange(t.id)}
          className={cn(
            "flex min-h-11 shrink-0 items-center gap-2 px-5 font-meta text-[0.6rem] font-bold tracking-[0.1em] transition-colors",
            t.id === tab
              ? "bg-ink-black text-bristol"
              : "text-ink-muted hover:text-ink-black",
          )}
        >
          {t.label}
          <ShortcutHint>{t.shortcut}</ShortcutHint>
        </button>
      ))}
    </div>
  );

  const actions = (
    <div className="flex shrink-0 items-center gap-2 px-3">
      {pageCount != null && (
        <span className="font-meta text-[0.56rem] font-bold tracking-[0.08em] text-ink-muted">
          {pageCount}P
        </span>
      )}
      {issueChipLabel && (
        <button
          type="button"
          onClick={onOpenIssues}
          className={cn(
            "flex min-h-11 items-center gap-1.5 border-[2px] px-3 font-meta text-[0.56rem] font-bold tracking-[0.08em] transition-colors",
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
        rerunAction={rerunAction}
      />
    </div>
  );

  // Identity + (on md+) tabs and actions live in the shell masthead; on
  // mobile the tabs/actions drop to their own in-flow bar below it.
  return (
    <>
      <TopBarPortal>
        <div className="relative flex min-w-0 flex-1 items-stretch overflow-hidden">
          <div className="hidden w-[68px] shrink-0 flex-col items-center justify-center bg-ink-black text-bristol lg:flex">
            <span className="font-meta text-[0.46rem] font-bold tracking-[0.14em] text-bristol/65">STATION</span>
            <strong className="mt-1 font-display text-[1.5rem] font-black leading-none tracking-[-0.03em]">04</strong>
          </div>
          <div className="flex shrink-0 flex-col items-start justify-center gap-1 px-4 pb-1 md:px-5">
            <span className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.14em] text-hero-red">
              BOOK
            </span>
            <h1 className="font-display text-[1.55rem] font-black uppercase leading-[0.9] tracking-[-0.03em] text-ink-black">
              FINISH &amp; EXPORT
            </h1>
          </div>
          <div className="hidden min-w-0 flex-1 items-stretch pb-1 xl:flex">
            {tabRow}
            {actions}
          </div>
          <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-[4px] bg-hero-red">
            <span className="absolute bottom-0 right-0 h-[4px] w-2 bg-narrator-gold" />
          </div>
        </div>
      </TopBarPortal>

      <div className="flex min-h-12 shrink-0 flex-wrap items-stretch border-b-[2px] border-ink-black bg-bristol xl:hidden">
        <div className="flex h-12 min-w-[13rem] flex-1 items-stretch">{tabRow}</div>
        <div className="ml-auto flex h-12 items-center">{actions}</div>
      </div>
    </>
  );
}

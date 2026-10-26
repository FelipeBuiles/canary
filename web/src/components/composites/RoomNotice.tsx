import { type ReactNode, useEffect, useId, useRef, useState } from "react";
import { ChevronDown, X } from "lucide-react";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";

export type RoomNoticeTone = "danger" | "attention" | "working";

const TONE: Record<RoomNoticeTone, { chip: string; mark: string }> = {
  danger: { chip: "border-hero-red/35 bg-chip-red text-status-blocked-text hover:border-hero-red/60", mark: "bg-hero-red" },
  attention: { chip: "border-ink-black/20 bg-chip-gold text-ink-black hover:border-ink-black/45", mark: "border border-ink-black bg-narrator-gold" },
  working: { chip: "border-ink-black/15 bg-bristol text-ink-black hover:border-ink-black/40", mark: "animate-press-blink bg-hero-red" },
};

/**
 * One line of room status that opens its details over the room instead of
 * pushing the work down. The chip says what happened; the panel holds the
 * list, the explanation and the actions.
 */
export function RoomNotice({ tone, label, title, children, role, defaultOpen = false, align = "start" }: {
  tone: RoomNoticeTone;
  /** The chip's text: what happened, in a few words. */
  label: ReactNode;
  /** The panel's heading and the notice's accessible name. */
  title: string;
  children: ReactNode;
  /** "alert" for failures that stop the room, "status" for progress. */
  role?: "alert" | "status";
  defaultOpen?: boolean;
  /** "end" opens the panel leftward, for a chip at the right edge of a toolbar. */
  align?: "start" | "end";
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(defaultOpen);
  const wrapper = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const titleId = useId();
  const styles = TONE[tone];

  useEffect(() => {
    if (!open) return;
    const onPointer = (event: PointerEvent) => {
      // Confirmations opened from the panel render outside it; only clicks on the room close it.
      const target = event.target as Node | null;
      if (target && !wrapper.current?.contains(target) && !(target as Element).closest?.("[role=dialog],[role=alertdialog]")) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpen(false);
      trigger.current?.focus();
    };
    document.addEventListener("pointerdown", onPointer);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("pointerdown", onPointer);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={wrapper} role={role} aria-labelledby={titleId} className="relative">
      <span id={titleId} className="sr-only">{title}</span>
      <button ref={trigger} type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen((value) => !value)}
        className={cn("inline-flex h-8 max-w-[min(100%,36rem)] items-center gap-2 border px-3 font-meta text-[0.8125rem] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-hero-red", styles.chip)}>
        <span aria-hidden="true" className={cn("size-2 shrink-0", styles.mark)} />
        <span className="min-w-0 truncate">{label}</span>
        <ChevronDown size={14} aria-hidden="true" className={cn("shrink-0 transition-transform", open && "rotate-180")} />
      </button>
      {open && (
        <div id={panelId}
          className={cn("absolute top-full z-40 mt-2 max-h-[min(40rem,calc(100dvh-10rem))] w-[min(34rem,calc(100vw-2rem))] overflow-y-auto border border-ink-black bg-bristol text-ink-black shadow-float", align === "end" ? "right-0" : "left-0")}>
          <div className="sticky top-0 z-10 flex items-center justify-between gap-3 border-b border-ink-black/10 bg-bristol px-4 py-2.5">
            <h2 className="font-meta text-sm font-semibold">{title}</h2>
            <button type="button" onClick={() => { setOpen(false); trigger.current?.focus(); }} aria-label={t("Close")} title={t("Close")}
              className="flex size-8 items-center justify-center text-ink-muted hover:text-ink-black focus-visible:outline-2 focus-visible:outline-hero-red">
              <X size={16} aria-hidden="true" />
            </button>
          </div>
          <div className="px-4 py-3">{children}</div>
        </div>
      )}
    </div>
  );
}

/** The single row that holds a room's notices, under the masthead. */
export function RoomNoticeRow({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2 border-b border-ink-black/10 px-4 py-2 sm:px-6 studio-desktop:px-5", className)}>
      {children}
    </div>
  );
}

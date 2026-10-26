import { useRef, useState } from "react";
import { Check, Pencil } from "lucide-react";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { FieldLabel, TextAreaField } from "../ui/Field";

type Layout = "list" | "numbered" | "cards" | "quote";

/**
 * One section of the brief document: readable by default, with an explicit,
 * keyboard-accessible edit mode. `cards` sets promises as numbered cards,
 * `numbered` sets events as a timeline, `quote` sets the tone on ink.
 */
export function BriefSection({ id, title, value, onChange, featured = false, numbered = false, quote = false }: {
  id: string;
  title: string;
  value: string | string[];
  onChange: (value: string) => void;
  featured?: boolean;
  /** Ordered requirements (essential events) read as a numbered sequence. */
  numbered?: boolean;
  quote?: boolean;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const toggle = useRef<HTMLDivElement>(null);
  const items = Array.isArray(value) ? value.filter((item) => item.trim()) : [];
  const layout: Layout = quote ? "quote" : featured ? "cards" : numbered ? "numbered" : "list";
  const onInk = layout === "quote";
  const empty = <p className={cn("font-body text-sm", onInk ? "text-bristol/70" : "text-ink-muted")}>{t("Nothing specified yet. Edit to add your direction.")}</p>;
  return (
    <section id={`brief-${id}`}
      className={cn("scroll-mt-6", onInk ? "relative bg-ink-black py-5 pl-14 pr-5 text-bristol sm:pl-16 sm:pr-6" : "border-t border-ink-black/12 pt-8")}>
      {onInk && <span aria-hidden="true" className="absolute left-4 top-1 font-display text-[4.5rem] font-black leading-none text-narrator-gold">“</span>}
      <div ref={toggle} className="mb-4 flex items-center gap-3">
        <h3 id={`${id}-title`} className={onInk
          ? "font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-bristol/70"
          : "font-display text-[1.3125rem] font-black uppercase leading-none tracking-[-0.02em]"}>{title}</h3>
        {!onInk && items.length > 0 && <span className="font-meta text-xs text-ink-muted">{items.length}</span>}
        <button type="button" aria-expanded={editing} aria-controls={`${id}-content`}
          aria-label={`${t(editing ? "Done editing" : "Edit")} ${title}`}
          onClick={() => setEditing(!editing)}
          className={cn(
            "ml-auto inline-flex min-h-8 items-center gap-1.5 border border-transparent px-2.5 font-meta text-[0.8125rem] font-medium",
            onInk ? "text-bristol/70 hover:border-bristol/30 hover:text-bristol"
              : "text-ink-muted hover:border-ink-black/25 hover:bg-bristol hover:text-ink-black",
            editing && (onInk ? "border-bristol/30 text-bristol" : "border-ink-black/25 bg-bristol text-ink-black"),
          )}>
          {editing ? <Check size={14} aria-hidden="true" /> : <Pencil size={13} aria-hidden="true" />}
          {t(editing ? "Done editing" : "Edit")}
        </button>
      </div>
      <div id={`${id}-content`}>
        {editing ? <>
          <FieldLabel htmlFor={id} className="sr-only">{title}</FieldLabel>
          <TextAreaField id={id} autoFocus value={Array.isArray(value) ? value.join("\n") : value}
            rows={Math.min(14, Math.max(4, (Array.isArray(value) ? value.length : 2) * 2))}
            className={onInk ? "text-ink-black" : undefined}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setEditing(false); toggle.current?.querySelector("button")?.focus(); } }}
            aria-describedby={`${id}-hint`} />
          <p id={`${id}-hint`} className={cn("mt-2 font-body text-xs leading-5", onInk ? "text-bristol/70" : "text-ink-muted")}>{t(Array.isArray(value) ? "One item per line. Use Save brief to keep your changes." : "Use Save brief to keep your changes.")}</p>
        </> : !Array.isArray(value) ? (
          value ? <p className={cn("whitespace-pre-wrap break-words font-body", onInk ? "text-lg font-medium leading-[1.6]" : "text-[0.9375rem] leading-7")}>{value}</p> : empty
        ) : !items.length ? empty : layout === "cards" ? (
          <ul className="grid gap-3 sm:grid-cols-2">
            {items.map((item, index) => <li key={index} className="border border-ink-black/14 bg-bristol px-4 pb-4 pt-3.5">
              <span aria-hidden="true" className="block font-display text-[1.75rem] font-black leading-none text-hero-red">{String(index + 1).padStart(2, "0")}</span>
              <p className="mt-2.5 whitespace-pre-wrap break-words font-body text-sm leading-[1.6]">{item}</p>
            </li>)}
          </ul>
        ) : layout === "numbered" ? (
          <ol>
            {items.map((item, index) => <li key={index} className="relative flex gap-3.5 pb-3.5 before:absolute before:bottom-0 before:left-[0.8125rem] before:top-6 before:w-px before:bg-ink-black/18 last:before:hidden">
              <span aria-hidden="true" className="inline-flex h-[1.375rem] min-w-[1.6875rem] shrink-0 items-center justify-center border border-ink-black bg-bristol px-1 font-meta text-[0.6875rem] font-bold tabular-nums">{String(index + 1).padStart(2, "0")}</span>
              <p className="min-w-0 whitespace-pre-wrap break-words font-body text-sm leading-[1.6]">{item}</p>
            </li>)}
          </ol>
        ) : (
          <ul className="space-y-2.5">
            {items.map((item, index) => <li key={index} className="flex gap-3">
              <span aria-hidden="true" className="mt-2.5 h-1.5 w-1.5 shrink-0 bg-hero-red" />
              <p className="min-w-0 whitespace-pre-wrap break-words font-body text-[0.9375rem] leading-[1.65]">{item}</p>
            </li>)}
          </ul>
        )}
      </div>
    </section>
  );
}

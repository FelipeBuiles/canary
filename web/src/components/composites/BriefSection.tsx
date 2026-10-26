import { useRef, useState, type ReactNode } from "react";
import { Check, ChevronDown, Pencil } from "lucide-react";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { FieldLabel, TextAreaField } from "../ui/Field";

/**
 * One section of the brief document: readable by default, with an explicit,
 * keyboard-accessible edit mode. `children` replaces the default read view
 * (a bulleted list or a paragraph). `collapsible` sets the section as one
 * direction row: a one-line summary that opens to the full text.
 */
export function BriefSection({ id, title, heading = title, value, onChange, stamp, lede, editLabel, children, collapsible = false, open = true, onOpenChange }: {
  id: string;
  /** Names the textarea and the Edit button for assistive technology. */
  title: string;
  /** The visible heading; defaults to the title. */
  heading?: string;
  value: string | string[];
  onChange: (value: string) => void;
  /** A small ink stamp, such as "Must keep", for sections Adapt enforces. */
  stamp?: string;
  lede?: string;
  editLabel?: string;
  children?: ReactNode;
  collapsible?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const toggle = useRef<HTMLButtonElement>(null);
  const items = Array.isArray(value) ? value.filter((item) => item.trim()) : [];
  const showing = !collapsible || open || editing;
  const empty = <p className="font-body text-sm text-ink-muted">{t("Nothing specified yet. Edit to add your direction.")}</p>;
  const editButton = (
    <button ref={toggle} type="button" aria-expanded={editing} aria-controls={`${id}-content`}
      aria-label={`${t(editing ? "Done editing" : "Edit")} ${title}`}
      onClick={() => {
        if (!editing) onOpenChange?.(true);
        setEditing(!editing);
      }}
      className={cn(
        "inline-flex min-h-8 shrink-0 items-center gap-1.5 border border-transparent px-2.5 font-meta text-[0.8125rem] font-medium text-ink-muted hover:border-ink-black/25 hover:bg-bristol hover:text-ink-black",
        editing && "border-ink-black/25 bg-bristol text-ink-black",
      )}>
      {editing ? <Check size={14} aria-hidden="true" /> : <Pencil size={13} aria-hidden="true" />}
      {t(editing ? "Done editing" : editLabel ?? "Edit")}
    </button>
  );
  const content = (
    <div id={`${id}-content`}>
      {editing ? <>
        <FieldLabel htmlFor={id} className="sr-only">{title}</FieldLabel>
        <TextAreaField id={id} autoFocus value={Array.isArray(value) ? value.join("\n") : value}
          rows={Math.min(14, Math.max(4, (Array.isArray(value) ? value.length : 2) * 2))}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setEditing(false); toggle.current?.focus(); } }}
          aria-describedby={`${id}-hint`} />
        <p id={`${id}-hint`} className="mt-2 font-body text-xs leading-5 text-ink-muted">{t(Array.isArray(value) ? "One item per line. Use Save brief to keep your changes." : "Use Save brief to keep your changes.")}</p>
      </> : children ?? (!Array.isArray(value) ? (
        value ? <p className="whitespace-pre-wrap break-words font-body text-[0.9375rem] leading-7">{value}</p> : empty
      ) : !items.length ? empty : (
        <ul className="space-y-2.5">
          {items.map((item, index) => <li key={index} className="flex gap-3">
            <span aria-hidden="true" className="mt-2.5 h-1.5 w-1.5 shrink-0 bg-hero-red" />
            <p className="min-w-0 whitespace-pre-wrap break-words font-body text-[0.9375rem] leading-[1.65]">{item}</p>
          </li>)}
        </ul>
      ))}
    </div>
  );

  if (collapsible) {
    const summary = Array.isArray(value) ? items.join(" · ") : value;
    return (
      <section id={`brief-${id}`} aria-labelledby={`${id}-title`} className="scroll-mt-6 border-t border-ink-black/9 first:border-t-0">
        <div className="flex items-start gap-2 pr-2">
          <button type="button" aria-expanded={showing} aria-controls={`${id}-content`} onClick={() => onOpenChange?.(!open)}
            className="grid min-w-0 flex-1 grid-cols-[9.5rem_minmax(0,1fr)_auto] items-start gap-3.5 py-3 pl-4 text-left hover:bg-surface-container/60">
            <span id={`${id}-title`} className="font-meta text-[0.8125rem] font-semibold leading-5 text-ink-black">
              {heading}{items.length > 0 && <span className="ml-1.5 font-medium text-ink-muted">{items.length}</span>}
            </span>
            <span className="min-w-0 truncate font-body text-[0.84375rem] leading-5 text-ink-soft">{showing ? null : summary || t("Not set")}</span>
            <ChevronDown size={14} aria-hidden="true" className={cn("mt-0.5 text-ink-muted transition-transform", showing && "rotate-180")} />
          </button>
          <div className="pt-1.5">{editButton}</div>
        </div>
        {showing && <div className="px-4 pb-4">{content}</div>}
      </section>
    );
  }

  return (
    <section id={`brief-${id}`} aria-labelledby={`${id}-title`} className="scroll-mt-6 border-t border-ink-black/12 pt-8 first:border-t-0 first:pt-0">
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2">
        <h3 id={`${id}-title`} className="font-display text-[1.5rem] font-black uppercase leading-none tracking-[-0.025em]">{heading}</h3>
        {items.length > 0 && <span className="font-meta text-[0.8125rem] text-ink-muted">{items.length}</span>}
        <span className="ml-auto flex items-center gap-2">
          {stamp && <span className="inline-flex h-[1.375rem] items-center gap-1.5 bg-ink-black px-2 font-meta text-[0.65625rem] font-bold uppercase tracking-[0.1em] text-pulp-paper">
            <span aria-hidden="true" className="h-1.5 w-1.5 bg-hero-red" />{stamp}
          </span>}
          {editButton}
        </span>
      </div>
      {lede && <p className="mb-4 mt-2 max-w-[38rem] font-body text-sm leading-[1.5] text-ink-soft">{lede}</p>}
      {!lede && <div className="h-4" />}
      {content}
    </section>
  );
}

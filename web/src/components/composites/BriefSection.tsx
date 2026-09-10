import { useRef, useState } from "react";
import { Check, Pencil } from "lucide-react";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { FieldLabel, TextAreaField } from "../ui/Field";
import { EntityCard } from "./EntityCard";

/** Readable editorial content with an explicit, keyboard-accessible edit mode. */
export function BriefSection({ id, title, value, onChange, featured = false }: {
  id: string;
  title: string;
  value: string | string[];
  onChange: (value: string) => void;
  featured?: boolean;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const toggle = useRef<HTMLDivElement>(null);
  const items = Array.isArray(value) ? value.filter((item) => item.trim()) : [];
  return (
    <EntityCard className={featured ? "shadow-paper" : ""}>
      <div ref={toggle} className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h3 className="font-display text-xl font-black uppercase leading-tight">{title}</h3>
        <Button variant="outline" size="xs" aria-expanded={editing} aria-controls={`${id}-content`}
          aria-label={`${t(editing ? "Done editing" : "Edit")} ${title}`}
          onClick={() => setEditing(!editing)}>
          {editing ? <Check size={14} aria-hidden="true" /> : <Pencil size={14} aria-hidden="true" />}
          {t(editing ? "Done editing" : "Edit")}
        </Button>
      </div>
      <div id={`${id}-content`}>
        {editing ? <>
          <FieldLabel htmlFor={id} className="sr-only">{title}</FieldLabel>
          <TextAreaField id={id} autoFocus value={Array.isArray(value) ? value.join("\n") : value}
            rows={Math.min(14, Math.max(4, (Array.isArray(value) ? value.length : 2) * 2))}
            onChange={(event) => onChange(event.target.value)}
            onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setEditing(false); toggle.current?.querySelector("button")?.focus(); } }}
            aria-describedby={`${id}-hint`} />
          <p id={`${id}-hint`} className="mt-2 font-body text-xs leading-5 text-ink-muted">{t(Array.isArray(value) ? "One item per line. Use Save brief to keep your changes." : "Use Save brief to keep your changes.")}</p>
        </> : Array.isArray(value) ? items.length ? <ul className="space-y-4">
          {items.map((item, index) => <li key={index} className="flex gap-3">
            <span aria-hidden="true" className="mt-2.5 h-1.5 w-1.5 shrink-0 bg-hero-red" />
            <p className={`max-w-[70ch] whitespace-pre-wrap break-words font-body ${featured ? "text-base leading-7" : "text-sm leading-6"}`}>{item}</p>
          </li>)}
        </ul> : <p className="font-body text-sm text-ink-muted">{t("Nothing specified yet. Edit to add your direction.")}</p>
          : <p className="max-w-[70ch] whitespace-pre-wrap break-words font-body text-sm leading-7">{value || t("Nothing specified yet. Edit to add your direction.")}</p>}
      </div>
    </EntityCard>
  );
}

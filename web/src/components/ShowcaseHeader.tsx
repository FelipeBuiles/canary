import type { ReactNode } from "react";
import { cn } from "../lib/cn";
import { useI18n } from "../i18n";

/**
 * Standard room-page header: chip label + big display title + optional lead copy.
 * Matches the "THE LIVING INK" masthead pattern in the spec.
 */
export function ShowcaseHeader({
  label,
  labelTone = "red",
  title,
  lead,
  actions,
  className,
}: {
  label: string;
  labelTone?: "red" | "gold" | "sage" | "ink" | "bristol";
  title: string;
  lead?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  const { t } = useI18n();
  return (
    <section
      className={cn(
        "border-[2px] border-ink-black bg-bristol px-7 py-6 md:px-8 md:py-7",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-6">
        <div
          className={cn(
            "inline-flex min-h-7 items-center px-3 py-1 font-meta text-[0.5rem] tracking-[0.22em] uppercase",
            labelTone === "gold" ? "bg-narrator-gold text-ink-black" :
            labelTone === "sage" ? "bg-archive-sage" :
            labelTone === "ink" ? "bg-ink-black" :
            labelTone === "bristol" ? "border border-ink-black/20 bg-bristol text-ink-black" :
            "bg-hero-red text-bristol",
          )}
        >
          {t(label)}
        </div>
        {actions ? <div className="flex flex-wrap items-center justify-end gap-2">{actions}</div> : null}
      </div>
      <h1 className="mt-3 font-display text-[clamp(2.6rem,4.4vw,4.25rem)] font-black uppercase leading-[0.82] tracking-[-0.06em] text-ink-black [font-stretch:75%]">
        {t(title)}
      </h1>
      {lead && (
        <div className="mt-2.5 max-w-[72rem] border-l-[3px] border-hero-red pl-3 text-[0.9rem] leading-7 text-ink-black/62 md:text-[0.95rem]">
          {typeof lead === "string" ? t(lead) : lead}
        </div>
      )}
    </section>
  );
}

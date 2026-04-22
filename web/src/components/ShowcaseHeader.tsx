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
    <section className={cn("border-[2px] border-ink-black bg-bristol px-6 py-7 md:px-10 md:py-10", className)}>
      <div className="flex items-start justify-between gap-4">
        <div
          className={cn(
            "inline-flex px-4 py-1.5 font-meta text-[0.56rem] tracking-[0.22em] uppercase text-bristol",
            labelTone === "gold" ? "bg-narrator-gold text-ink-black" :
            labelTone === "sage" ? "bg-archive-sage" :
            labelTone === "ink" ? "bg-ink-black" :
            labelTone === "bristol" ? "border-[2px] border-ink-black bg-bristol text-ink-black" :
            "bg-hero-red",
          )}
        >
          {t(label)}
        </div>
        {actions}
      </div>
      <h1 className="mt-4 font-display text-[clamp(3rem,5vw,4.5rem)] font-black uppercase leading-[0.82] tracking-[-0.055em] text-ink-black [font-stretch:75%]">
        {t(title)}
      </h1>
      {lead && (
        <div className="mt-5 max-w-[56rem] border-l-[4px] border-hero-red pl-5 text-[1.05rem] leading-[1.6] text-ink-black/72 md:text-[1.25rem]">
          {typeof lead === "string" ? t(lead) : lead}
        </div>
      )}
    </section>
  );
}

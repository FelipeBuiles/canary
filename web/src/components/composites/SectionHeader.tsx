import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";

type SectionHeaderVariant = "rule" | "underline";

interface SectionHeaderProps {
  title: string;
  kicker?: string;
  description?: ReactNode;
  actions?: ReactNode;
  variant?: SectionHeaderVariant;
  className?: string;
}

export function SectionHeader({
  title,
  kicker,
  description,
  actions,
  variant = "rule",
  className,
}: SectionHeaderProps) {
  const { t } = useI18n();

  if (variant === "rule") {
    return (
      <header className={cn("mb-6 border-b-[2px] border-ink-black pb-3", className)}>
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
          {kicker && (
            <span className="bg-narrator-gold px-2 py-1 font-meta text-[0.58rem] font-bold uppercase tracking-[0.12em] text-ink-black">
              {t(kicker)}
            </span>
          )}
          <h2 className="font-display text-[1.35rem] font-black uppercase leading-none tracking-[-0.03em] text-ink-black">
            {t(title)}
          </h2>
          {actions && <span className="ml-auto flex items-center gap-2">{actions}</span>}
        </div>
        {description && (
          <p className="mt-2 font-body text-[0.9rem] leading-6 text-ink-black/70">
            {typeof description === "string" ? t(description) : description}
          </p>
        )}
      </header>
    );
  }

  return (
    <header className={cn("relative mb-7 border-b-[3px] border-ink-black pb-4", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          {kicker && (
            <div className="font-meta text-[0.68rem] font-bold tracking-[0.12em] text-ink-black/65">
              {t(kicker)}
            </div>
          )}
          <h2 className="font-display text-[1.9rem] font-black uppercase leading-none tracking-[-0.035em] text-ink-black">
            {t(title)}
          </h2>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {description && (
        <p className="mt-2 font-body text-[0.9rem] leading-6 text-ink-black/70">
          {typeof description === "string" ? t(description) : description}
        </p>
      )}
      <span aria-hidden="true" className="absolute -bottom-[3px] left-0 h-[3px] w-14 bg-hero-red" />
    </header>
  );
}

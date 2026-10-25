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
      <header className={cn("mb-4 border-b border-ink-black/12 pb-2", className)}>
        <div className="flex flex-wrap items-end gap-x-4 gap-y-2">
          {kicker && (
            <span className="bg-narrator-gold px-2 py-1 font-meta text-[0.58rem] font-bold uppercase tracking-[0.12em] text-ink-black">
              {t(kicker)}
            </span>
          )}
          <h2 className="font-display text-[1.125rem] font-black uppercase leading-none tracking-[-0.02em] text-ink-black">
            {t(title)}
          </h2>
          {actions && <span className="ml-auto flex items-center gap-2">{actions}</span>}
        </div>
        {description && (
          <p className="mt-1.5 font-body text-[0.8125rem] leading-5 text-ink-muted">
            {typeof description === "string" ? t(description) : description}
          </p>
        )}
      </header>
    );
  }

  return (
    <header className={cn("relative mb-4 border-b border-ink-black/12 pb-2.5", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          {kicker && (
            <div className="font-meta text-[0.68rem] font-bold tracking-[0.12em] text-ink-black/65">
              {t(kicker)}
            </div>
          )}
          <h2 className="font-display text-[1.25rem] font-black uppercase leading-none tracking-[-0.025em] text-ink-black">
            {t(title)}
          </h2>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {description && (
        <p className="mt-1.5 font-body text-[0.8125rem] leading-5 text-ink-muted">
          {typeof description === "string" ? t(description) : description}
        </p>
      )}
      <span aria-hidden="true" className="absolute -bottom-px left-0 h-[2px] w-10 bg-hero-red" />
    </header>
  );
}

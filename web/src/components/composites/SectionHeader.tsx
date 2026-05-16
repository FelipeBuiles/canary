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
      <header className={cn("mb-6", className)}>
        <div className="section-rule">
          {kicker && (
            <>
              <span className="font-meta text-ink-black">{t(kicker)}</span>
              <span className="text-ink-black/45">//</span>
            </>
          )}
          <span className="font-meta text-ink-black/80">{t(title)}</span>
          {actions && <span className="ml-auto flex items-center gap-2">{actions}</span>}
        </div>
        {description && (
          <p className="mt-2 max-w-[72ch] font-body text-[0.9rem] leading-6 text-ink-black/62">
            {description}
          </p>
        )}
      </header>
    );
  }

  return (
    <header className={cn("mb-7 border-b-[2px] border-ink-black pb-4", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2">
        <div className="flex flex-wrap items-baseline gap-x-4 gap-y-2">
          {kicker && (
            <div className="font-meta text-[0.82rem] tracking-[0.24em] text-ink-black/52">
              {t(kicker)}
            </div>
          )}
          <h2 className="font-display text-[2.25rem] font-bold uppercase leading-none tracking-[-0.06em] text-ink-black">
            {t(title)}
          </h2>
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {description && (
        <p className="mt-2 max-w-[72ch] font-body text-[0.9rem] leading-6 text-ink-black/62">
          {description}
        </p>
      )}
    </header>
  );
}

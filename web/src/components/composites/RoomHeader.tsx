import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";

const CompactIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="1" y="1" width="12" height="2" stroke="currentColor" strokeWidth="1.5" />
    <rect x="1" y="5" width="12" height="8" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

const ExpandIcon = () => (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="1" y="1" width="12" height="3" stroke="currentColor" strokeWidth="1.5" />
    <rect x="1" y="6" width="12" height="7" stroke="currentColor" strokeWidth="1.5" />
  </svg>
);

/**
 * Unified stage page header. The compact prop is the sole layout controller —
 * no responsive breakpoint overrides. Pass onToggle to show the toggle button.
 */
export function RoomHeader({
  kicker,
  title,
  lead,
  actions,
  compact,
  onToggle,
  className,
}: {
  kicker: string;
  title: string;
  lead?: ReactNode;
  actions?: ReactNode;
  compact?: boolean;
  onToggle?: () => void;
  className?: string;
}) {
  const { t } = useI18n();

  const toggleBtn = onToggle ? (
    <button
      type="button"
      onClick={onToggle}
      title={compact ? "Expand header" : "Compact header"}
      className="flex h-7 w-7 shrink-0 items-center justify-center text-ink-black/35 transition-colors hover:text-ink-black/70"
    >
      {compact ? <ExpandIcon /> : <CompactIcon />}
    </button>
  ) : null;

  if (compact) {
    return (
      <header
        className={cn(
          "flex h-14 shrink-0 items-center gap-0 border-b-[2px] border-ink-black bg-bristol px-5",
          className,
        )}
      >
        <span className="shrink-0 bg-hero-red px-3 py-1 font-meta text-[0.56rem] tracking-[0.22em] uppercase text-bristol">
          {t(kicker)}
        </span>

        <span className="mx-4 h-4 w-px shrink-0 bg-ink-black/20" />

        <span className="shrink-0 font-display text-[1.12rem] font-black uppercase leading-none tracking-[-0.03em] text-ink-black [font-stretch:75%]">
          {t(title)}
        </span>

        {lead && (
          <span className="ml-3 min-w-0 border-l-[2px] border-hero-red/40 pl-3 font-body text-[0.78rem] leading-tight text-ink-black/68 line-clamp-2">
            {typeof lead === "string" ? t(lead) : lead}
          </span>
        )}

        <div className="ml-auto flex shrink-0 items-center gap-2">
          {actions}
          {toggleBtn}
        </div>
      </header>
    );
  }

  return (
    <section
      className={cn(
        "shrink-0 border-[2px] border-ink-black bg-bristol px-7 py-6 md:px-8 md:py-7",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-6">
        <span className="inline-flex min-h-7 items-center bg-hero-red px-3 py-1 font-meta text-[0.5rem] tracking-[0.22em] uppercase text-bristol">
          {t(kicker)}
        </span>
        {(actions || toggleBtn) && (
          <div className="flex flex-wrap items-center justify-end gap-2">
            {actions}
            {toggleBtn}
          </div>
        )}
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

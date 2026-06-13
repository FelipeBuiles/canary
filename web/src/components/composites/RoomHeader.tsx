import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";
import { TopBarPortal } from "../../layout/TopBarSlot";

/**
 * Unified stage page header. Renders into the shell masthead (AppTopBar slot)
 * rather than occupying its own bar in the content flow: kicker stacked above
 * a display title on the left, lead alongside, actions on the right.
 */
export function RoomHeader({
  kicker,
  title,
  lead,
  actions,
  className,
}: {
  kicker: string;
  title: string;
  lead?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  const { t } = useI18n();

  return (
    <>
      <TopBarPortal>
        <div className={cn("flex min-w-0 flex-1 items-center gap-5 px-4 md:px-5", className)}>
          <div className="flex min-w-0 flex-col items-start justify-center gap-1.5 md:max-w-[42%] md:shrink-0">
            <span className="bg-hero-red px-2.5 py-[3px] font-meta text-[0.5rem] tracking-[0.22em] uppercase text-bristol">
              {t(kicker)}
            </span>
            <h1 className="max-w-full truncate font-display text-[1.55rem] font-black uppercase leading-[0.85] tracking-[-0.04em] text-ink-black [font-stretch:75%]" title={t(title)}>
              {t(title)}
            </h1>
          </div>

          {lead && (
            <span className="hidden min-w-0 max-w-[46rem] border-l-[3px] border-hero-red pl-3 font-body text-[0.8rem] leading-snug text-ink-black/62 line-clamp-2 lg:[display:-webkit-box]">
              {typeof lead === "string" ? t(lead) : lead}
            </span>
          )}

          {actions && (
            <div className="ml-auto hidden shrink-0 items-center gap-2 pl-3 md:flex">
              {actions}
            </div>
          )}
        </div>
      </TopBarPortal>

      {/* On mobile the masthead only fits kicker + title; actions get their
          own full-width strip directly beneath it. */}
      {actions && (
        <div className="-mx-5 -mt-6 mb-2 flex flex-wrap items-center justify-end gap-2 border-b-[2px] border-ink-black/15 bg-bristol px-4 py-2 md:hidden">
          {actions}
        </div>
      )}
    </>
  );
}

import type { ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";
import { STATIONS, stationForRoute } from "../../lib/stations";
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
  const location = useLocation();
  const route = location.pathname.split("/").filter(Boolean).at(-1) ?? "";
  const station = stationForRoute(route);
  const stationIndex = station ? STATIONS.findIndex((item) => item.key === station.key) : -1;
  const progress = stationIndex >= 0 ? ((stationIndex + 1) / STATIONS.length) * 100 : 0;

  return (
    <>
      <TopBarPortal>
        <div className={cn("relative flex min-w-0 flex-1 items-stretch overflow-hidden", className)}>
          {station && (
            <div className="hidden w-[68px] shrink-0 flex-col items-center justify-center bg-ink-black text-bristol lg:flex">
              <span className="font-meta text-[0.46rem] font-bold tracking-[0.14em] text-bristol/65">{t("STATION")}</span>
              <strong className="mt-1 font-display text-[1.5rem] font-black leading-none tracking-[-0.03em]">
                {station.number}
              </strong>
            </div>
          )}

          <div className="flex min-w-0 flex-1 items-center gap-5 px-4 pb-1 md:px-5">
            <div className="flex min-w-0 flex-col items-start justify-center gap-1 lg:max-w-[42%] lg:shrink-0">
              <span className="font-meta text-[0.54rem] font-bold uppercase tracking-[0.14em] text-hero-red">
                {t(kicker)}
              </span>
              <h1 className="max-w-full truncate font-display text-[1.55rem] font-black uppercase leading-[0.9] tracking-[-0.03em] text-ink-black" title={t(title)}>
                {t(title)}
              </h1>
            </div>

            {lead && (
              <>
                <span aria-hidden="true" className="hidden h-8 w-[2px] shrink-0 bg-ink-black/16 lg:block" />
                <span className="hidden min-w-0 max-w-[46rem] font-body text-[0.8rem] font-semibold leading-snug text-ink-muted line-clamp-2 lg:[display:-webkit-box]">
                  {typeof lead === "string" ? t(lead) : lead}
                </span>
              </>
            )}

            {actions && (
              <div className="ml-auto hidden shrink-0 items-center gap-2 pl-3 md:flex">
                {actions}
              </div>
            )}
          </div>

          {station && (
            <div aria-hidden="true" className="absolute inset-x-0 bottom-0 h-[4px] bg-surface-variant">
              <span
                className="relative block h-full bg-hero-red transition-[width] duration-500 ease-[cubic-bezier(0.22,1,0.36,1)]"
                style={{ width: `${progress}%` }}
              >
                <span className="absolute -right-1 bottom-0 h-[4px] w-2 bg-narrator-gold" />
              </span>
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

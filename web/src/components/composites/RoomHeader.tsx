import type { ReactNode } from "react";
import { cn } from "../../lib/cn";
import { useI18n } from "../../i18n";
import { TopBarPortal } from "../../layout/TopBarSlot";

/**
 * Unified stage page header. Renders into the shell masthead (AppTopBar slot)
 * rather than occupying its own bar in the content flow: the room title, one
 * line of facts, and the room's actions. Station progress lives in the rail,
 * so the masthead never repeats it. Masthead width, not the viewport, decides
 * what fits: the title and actions keep priority; the meta line appears only
 * with room.
 */
export function RoomHeader({
  title,
  lead,
  actions,
  className,
}: {
  title: string;
  /** One line of facts ("16 pages · Two-Tone Woodcut Print"), not an explanation. */
  lead?: ReactNode;
  actions?: ReactNode;
  className?: string;
}) {
  const { t } = useI18n();

  return (
    <>
      <TopBarPortal inlineOnMobile>
        {/* Inline on phones; an edge-to-edge room has no sheet margins to inset it. */}
        <div className={cn("@container/masthead relative flex min-w-0 flex-1 items-center gap-4 in-data-bleed:px-4 in-data-bleed:py-4 sm:in-data-bleed:px-6 studio-desktop:px-5", className)}>
          <h1 className="min-w-0 max-w-full truncate font-display text-[1.75rem] font-black uppercase leading-[0.95] tracking-[-0.03em] text-ink-black [overflow-wrap:anywhere] sm:text-[2rem] studio-desktop:text-[1.625rem]" title={t(title)}>
            {t(title)}
          </h1>

          {lead && (
            <span className="hidden min-w-0 flex-[0_1_auto] truncate font-meta text-xs font-medium text-ink-soft @min-[40rem]/masthead:block">
              {typeof lead === "string" ? t(lead) : lead}
            </span>
          )}

          {actions && (
            <div className="ml-auto hidden shrink-0 items-center gap-2 pl-3 studio-desktop:flex">
              {actions}
            </div>
          )}
        </div>
      </TopBarPortal>

      {/* Compact room titles and tools scroll with their content. */}
      {actions && (
        <div className="mt-4 flex flex-wrap items-center gap-2 in-data-bleed:px-4 sm:in-data-bleed:px-6 studio-desktop:hidden">
          {actions}
        </div>
      )}
    </>
  );
}

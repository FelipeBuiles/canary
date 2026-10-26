import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { SHOT_LABELS, panelsInOrder, sketchTiers, withEntityNames, type EntityRef } from "../../lib/readingDocs";
import type { ComicPage } from "../../types/api";

/**
 * An undrawn page as a script sketch: the planned panels as boxes in reading
 * order, so the plan reads as a page before Draw has made one.
 */
export function PlanSketch({ page, names, size }: { page: ComicPage; names?: Map<string, EntityRef>; size: "stage" | "thumb" }) {
  const { t } = useI18n();
  const panels = panelsInOrder(page.content, page.reading_order);
  const tiers = sketchTiers(panels);
  const numberOf = new Map(panels.map((panel, index) => [panel.id, index + 1]));

  if (size === "thumb") {
    return (
      <span aria-hidden="true" className="flex h-full w-full flex-col gap-[2px] bg-bristol p-[3px]">
        {tiers.map((tier, row) => (
          <span key={row} className="flex min-h-0 flex-1 gap-[2px]">
            {tier.map((panel) => <span key={panel.id} className="min-w-0 flex-1 border border-ink-black/45" />)}
          </span>
        ))}
      </span>
    );
  }

  return (
    <figure aria-label={t("Planned layout of page {number}", { number: String(page.page_number) })}
      className="flex aspect-[2/3] h-[min(100%,52rem)] max-w-full flex-col bg-bristol p-3 shadow-[0_24px_60px_-20px_rgba(0,0,0,0.75)]">
      <div className="flex min-h-0 flex-1 flex-col gap-2">
        {tiers.map((tier, row) => (
          <div key={row} className="flex min-h-0 flex-1 gap-2">
            {tier.map((panel) => {
              const lines = panel.lettering.filter((line) => line.text);
              return (
                <div key={panel.id} className="relative flex min-w-0 flex-1 flex-col gap-1.5 overflow-hidden border-2 border-ink-black/80 bg-pulp-paper/60 p-2">
                  <div className="flex items-center gap-1.5">
                    <span className="flex h-5 w-5 shrink-0 items-center justify-center border border-ink-black bg-narrator-gold font-meta text-[0.625rem] font-bold tabular-nums">{numberOf.get(panel.id)}</span>
                    {panel.camera && <span className="truncate font-meta text-[0.625rem] font-semibold uppercase tracking-[0.06em] text-ink-muted">{t(SHOT_LABELS[panel.camera.shot])}</span>}
                  </div>
                  <p className="line-clamp-3 font-body text-[0.6875rem] leading-[1.35] text-ink-soft">{withEntityNames(names ?? new Map(), panel.visual_intent)}</p>
                  <div className="mt-auto flex min-h-0 flex-col gap-1 overflow-hidden">
                    {lines.slice(0, 2).map((line) => (
                      <p key={line.id} className={cn("line-clamp-2 px-1.5 py-0.5 font-body text-[0.625rem] leading-[1.3]",
                        line.kind === "caption" ? "border border-ink-black/60 bg-chip-gold"
                          : line.kind === "sfx" ? "font-display font-black uppercase text-hero-red"
                          : "rounded-lg border border-ink-black/60 bg-bristol")}>{line.text}</p>
                    ))}
                    {lines.length > 2 && <p className="font-meta text-[0.625rem] text-ink-muted">{t("+{count} more", { count: lines.length - 2 })}</p>}
                  </div>
                </div>
              );
            })}
          </div>
        ))}
      </div>
    </figure>
  );
}

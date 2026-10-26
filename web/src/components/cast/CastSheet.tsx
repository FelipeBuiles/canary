import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { ASPECT, thumbnailUrl, type CastEntry, type CastKind } from "./castAssets";
import type { CastAttention, RosterGroup } from "./CastRoster";
import { useCastEntryImage } from "./useCastEntryImage";

const COLUMNS: Record<CastKind, string> = {
  // At most five sheets or plates (eight props) per row, so wide screens grow the art instead of the gaps.
  character: "grid-cols-[repeat(auto-fill,minmax(max(13rem,calc((100%-4rem)/5)),1fr))]",
  location: "grid-cols-[repeat(auto-fill,minmax(max(13rem,calc((100%-4rem)/5)),1fr))]",
  prop: "grid-cols-[repeat(auto-fill,minmax(max(8.5rem,calc((100%-7rem)/8)),1fr))]",
};

function SheetTile({ project, entry, stageRegenerating, attention, onOpen }: {
  project: string;
  entry: CastEntry;
  stageRegenerating: boolean;
  attention?: CastAttention;
  onOpen: () => void;
}) {
  const { t } = useI18n();
  const image = useCastEntryImage(project, entry, stageRegenerating);
  return (
    <button type="button" onClick={onOpen} aria-busy={image.isGenerating || undefined}
      className="group min-w-0 text-left focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-narrator-gold">
      <span className="relative block overflow-hidden bg-ink-black outline outline-1 outline-pulp-paper/15 transition-[outline-color,transform,box-shadow] group-hover:-translate-y-px group-hover:shadow-[0_18px_30px_-16px_rgb(0_0_0/0.8)] group-hover:outline-pulp-paper/60"
        style={{ aspectRatio: String(ASPECT[entry.kind]) }}>
        {image.probe}
        {!image.missing && (
          <img src={thumbnailUrl(image.imageSrc, "card")} alt="" loading="lazy" onError={() => image.imageFailed()}
            className={cn("h-full w-full object-contain", image.isGenerating && "opacity-35")} />
        )}
        {(image.missing || image.isGenerating) && (
          <span className="benday-ink absolute inset-0 flex items-center justify-center gap-2 font-meta text-xs text-on-chrome-muted">
            {image.isGenerating ? <><span aria-hidden="true" className="size-2 bg-narrator-gold motion-safe:animate-pulse" />{t("Drawing…")}</> : t("No image yet")}
          </span>
        )}
        {attention && !image.isGenerating && (
          <span className={cn("absolute left-2 top-2 border px-1.5 font-meta text-[0.6875rem] font-bold uppercase leading-5 tracking-[0.04em]",
            attention === "failed" ? "border-hero-red bg-hero-red text-bristol" : "border-ink-black bg-narrator-gold text-ink-black")}>
            {attention === "failed" ? t("Didn't finish") : t("Out of date")}
          </span>
        )}
      </span>
      <span className="mt-2 block truncate font-meta text-[0.8125rem] font-semibold text-pulp-paper">{entry.entity.name}</span>
    </button>
  );
}

/** Every reference at once, grouped. Opening one takes it to the stage. */
export function CastSheet({ project, groups, stageRegenerating, attentionOf, onOpen }: {
  project: string;
  groups: RosterGroup[];
  stageRegenerating: boolean;
  attentionOf: (entry: CastEntry) => CastAttention | undefined;
  onOpen: (entry: CastEntry) => void;
}) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-8 pt-2 sm:px-7">
      {groups.map((group) => group.entries.length > 0 && (
        <section key={group.kind} aria-label={group.label} className="mb-7">
          <h2 className="mb-3 flex items-baseline gap-2 font-display text-lg font-black uppercase tracking-[-0.02em] text-pulp-paper">
            {group.label}<span className="font-meta text-xs font-medium tracking-normal text-on-chrome-muted">{group.entries.length}</span>
          </h2>
          <div className={cn("grid gap-x-4 gap-y-5", COLUMNS[group.kind])}>
            {group.entries.map((entry) => (
              <SheetTile key={entry.entity.id} project={project} entry={entry} stageRegenerating={stageRegenerating}
                attention={attentionOf(entry)} onOpen={() => onOpen(entry)} />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

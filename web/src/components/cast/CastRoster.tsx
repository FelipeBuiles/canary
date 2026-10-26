import { useId, useState, type ReactNode } from "react";
import { Search, X } from "lucide-react";
import { useI18n } from "../../i18n";
import { cn } from "../../lib/cn";
import { entryAnchor, portraitUrl, thumbnailUrl, type CastEntry, type CastKind } from "./castAssets";
import { useCastEntryImage } from "./useCastEntryImage";

/** What a roster row flags: a reference that didn't finish, or one whose image is out of date. */
export type CastAttention = "failed" | "outdated";

export interface RosterGroup {
  kind: CastKind;
  label: string;
  entries: CastEntry[];
}

const THUMB: Record<CastKind, string> = {
  character: "h-10 w-10",
  location: "h-8 w-14",
  prop: "h-10 w-10",
};

function RosterRow({ project, entry, sub, selected, stageRegenerating, attention, onSelect }: {
  project: string;
  entry: CastEntry;
  sub: string;
  selected: boolean;
  stageRegenerating: boolean;
  attention?: CastAttention;
  onSelect: () => void;
}) {
  const { t } = useI18n();
  const descriptionId = useId();
  const image = useCastEntryImage(project, entry, stageRegenerating);
  // Characters show the face crop pages use; older sheets without one fall back to the sheet.
  const [portraitFailed, setPortraitFailed] = useState(false);
  const usePortrait = entry.kind === "character" && !portraitFailed;
  const thumbSrc = thumbnailUrl(usePortrait ? `${portraitUrl(project, entry.entity.id)}?t=${encodeURIComponent(image.timestamp)}` : image.imageSrc);
  const status = image.isGenerating ? t("Drawing") : attention === "failed" ? t("Didn't finish") : attention === "outdated" ? t("Out of date") : null;

  return (
    <li>
      <button
        type="button"
        id={entryAnchor(entry.kind, entry.entity.id)}
        aria-label={entry.entity.name}
        aria-describedby={descriptionId}
        aria-current={selected ? "true" : undefined}
        aria-busy={image.isGenerating || undefined}
        onClick={onSelect}
        className={cn(
          "relative flex w-full items-center gap-3 py-2 pl-4 pr-3 text-left transition-colors focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-hero-red",
          selected ? "bg-ink-black text-pulp-paper" : "hover:bg-sidebar-tint",
        )}
      >
        {selected && <span aria-hidden="true" className="absolute inset-y-0 left-0 w-1 bg-hero-red" />}
        <span className={cn("relative shrink-0 overflow-hidden bg-surface-container", THUMB[entry.kind], selected ? "outline outline-1 outline-pulp-paper/30" : "outline outline-1 -outline-offset-1 outline-ink-black/12")}>
          {image.probe}
          {!image.missing && (
            <img
              key={thumbSrc}
              src={thumbSrc}
              alt=""
              loading="lazy"
              onError={() => usePortrait ? setPortraitFailed(true) : image.imageFailed()}
              className={cn("h-full w-full object-cover", entry.kind === "character" && !usePortrait && "object-[30%_20%]", image.isGenerating && "opacity-35")}
            />
          )}
          {(image.isGenerating || image.missing) && <span aria-hidden="true" className="benday-ink absolute inset-0 opacity-90" />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block truncate font-meta text-[0.8125rem] font-semibold leading-5">{entry.entity.name}</span>
          <span id={descriptionId} className={cn("block truncate font-body text-xs leading-4", selected ? "text-pulp-paper/65" : "text-ink-muted")}>
            {status && <span className="sr-only">{status} · </span>}{sub}
          </span>
        </span>
        {image.isGenerating ? (
          <span aria-hidden="true" title={t("Drawing")} className="size-2 shrink-0 bg-narrator-gold motion-safe:animate-pulse" />
        ) : attention && (
          <span aria-hidden="true" title={status ?? undefined}
            className={cn("flex size-5 shrink-0 items-center justify-center border font-meta text-xs font-bold",
              attention === "failed" ? "border-hero-red bg-hero-red text-bristol" : "border-ink-black bg-narrator-gold text-ink-black")}>
            !
          </span>
        )}
      </button>
    </li>
  );
}

/**
 * Every reference in one list. Selecting a row puts it on the stage; the
 * search narrows the list without losing the selection.
 */
export function CastRoster({ project, groups, subOf, selectedKey, stageRegenerating, attentionOf, search, onSearch, onSelect, children }: {
  project: string;
  groups: RosterGroup[];
  subOf: (entry: CastEntry) => string;
  selectedKey: string | null;
  stageRegenerating: boolean;
  attentionOf: (entry: CastEntry) => CastAttention | undefined;
  search: string;
  onSearch: (value: string) => void;
  onSelect: (entry: CastEntry) => void;
  /** Upkeep shown above the list, such as looks to update. */
  children?: ReactNode;
}) {
  const { t } = useI18n();
  const query = search.trim().toLocaleLowerCase();
  const visible = groups.map((group) => ({
    ...group,
    shown: group.entries.filter((entry) => entry.entity.name.toLocaleLowerCase().includes(query)),
  }));
  const matchCount = visible.reduce((sum, group) => sum + group.shown.length, 0);

  return (
    <aside aria-label={t("Cast list")} className="flex max-h-[22rem] shrink-0 flex-col border-b border-ink-black/12 bg-pulp-paper studio-desktop:max-h-none studio-desktop:w-64 studio-desktop:border-b-0 studio-desktop:border-r">
      <div className="shrink-0 px-3 pb-2 pt-3">
        <label htmlFor="cast-search" className="sr-only">{t("Find a reference")}</label>
        <div className="relative">
          <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-soft" />
          <input id="cast-search" type="search" value={search} onChange={(event) => onSearch(event.target.value)} placeholder={t("Find in cast")}
            className="h-9 w-full border border-ink-black/30 bg-bristol pl-8 pr-8 font-body text-[0.8125rem] text-ink-black outline-none placeholder:text-ink-soft focus:border-ink-black [&::-webkit-search-cancel-button]:hidden" />
          {search && (
            <button type="button" onClick={() => onSearch("")} aria-label={t("Clear search")} title={t("Clear search")}
              className="absolute right-1 top-1/2 flex size-7 -translate-y-1/2 items-center justify-center text-ink-muted hover:text-ink-black focus-visible:outline-2 focus-visible:outline-hero-red">
              <X size={14} aria-hidden="true" />
            </button>
          )}
        </div>
        {query && <p role="status" className="mt-1.5 font-meta text-[0.6875rem] text-ink-muted">{t("{count} references found", { count: String(matchCount) })}</p>}
      </div>
      {children}
      <div className="min-h-0 flex-1 overflow-y-auto pb-3">
        {query && matchCount === 0 && (
          <p className="benday-paper mx-3 mt-2 px-4 py-6 text-center font-body text-sm text-ink-muted">{t("No matching references. Try another name or clear your search.")}</p>
        )}
        {visible.map((group) => group.shown.length > 0 && (
          <section key={group.kind} aria-label={group.label} id={`cast-${group.kind === "character" ? "characters" : group.kind === "location" ? "places" : "props"}`}>
            <h2 className="flex items-baseline justify-between px-4 pb-1 pt-4 font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">
              <span>{group.label}</span><span className="tabular-nums">{group.entries.length}</span>
            </h2>
            <ul>
              {group.shown.map((entry) => {
                const key = `${entry.kind}:${entry.entity.id}`;
                return (
                  <RosterRow key={key} project={project} entry={entry} sub={subOf(entry)} selected={key === selectedKey}
                    stageRegenerating={stageRegenerating} attention={attentionOf(entry)} onSelect={() => onSelect(entry)} />
                );
              })}
            </ul>
          </section>
        ))}
      </div>
    </aside>
  );
}

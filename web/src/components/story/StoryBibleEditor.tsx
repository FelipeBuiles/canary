import { ErrorNotice } from "../composites/ErrorNotice";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, Pencil, Plus, Search, Undo2, X } from "lucide-react";
import { useI18n } from "../../i18n";
import { Sheet } from "../composites/Sheet";
import { Button } from "../ui/Button";
import { FieldLabel, TextField } from "../ui/Field";
import { EntitySheet } from "./EntitySheet";
import { KIND_LABELS } from "./entityKinds";
import { isNotFoundError } from "../../api/client";
import { splitProjectKey } from "../../api/projectScope";
import { castCharacters } from "../../lib/castRoster";
import { readableAnchor } from "../../lib/visualAnchor";
import { useProjectStatus } from "../../api/queries";
import { StoryScenes } from "./StoryScenes";
import { referencesToUpdate, UPDATE_REFERENCES_SEARCH } from "./castReferences";
import { known, narrativeScenes, readablePhrase, sceneNumbers } from "./storyPhrases";
import { cn } from "../../lib/cn";
import { mainImageUrl, portraitUrl, type CastKind } from "../cast/castAssets";
import {
  useEditImpact, useMergeEntity, useRemoveEntity, useRestoreExcluded, useStoryBibleEditor, useUndoEdit,
} from "../../api/seriesQueries";
import type { EditImpact, EntityKind, StoryBibleChange, StoryBibleEditor as Editor } from "../../api/storyBible";
import type { Character, ExcludedEntity, Location, Prop, Scene, StoryBible } from "../../types/api";

type Entry = {
  id: string; name: string; aliases?: string[]; origin?: string; visual_anchor: string;
  appearance_states?: { id: string; label: string }[];
};
type Translate = ReturnType<typeof useI18n>["t"];

const TAB_LABELS: Record<EntityKind, string> = { characters: "Characters", locations: "Places", props: "Props" };
const EXCLUDED_KIND: Record<ExcludedEntity["kind"], EntityKind> = { character: "characters", location: "locations", prop: "props" };

export interface EntityFocus { kind: EntityKind; id: string }

interface Props {
  project: string;
  /** This part's extracted story: adds its read-only scenes and keeps entries readable without the editor. */
  story?: StoryBible;
  /** Open one entity's editor, e.g. from Cast's "Edit details". */
  focus?: EntityFocus | null;
  onFocusClosed?: () => void;
}

type Open =
  | { mode: "edit"; kind: EntityKind; id?: string }
  | { mode: "merge"; kind: EntityKind; id: string; into?: string }
  | { mode: "remove"; kind: EntityKind; id: string };

/** Where entry cards look up scenes, names and parts. */
interface CardContext {
  project?: string;
  bible: StoryBible;
  editor?: Editor;
  /** This part's scenes, numbered in reading order. */
  partScenes: Scene[];
  numbers: Map<string, string>;
}

/**
 * The story at a glance and the author's view of the shared Story Bible:
 * a list of every entry beside this part's scene board. Picking an entry
 * shows where it appears and what the Bible holds for it; editing, merging
 * and removing happen in its sheet.
 */
export function StoryBibleEditor({ project, story, focus, onFocusClosed }: Props) {
  const { t } = useI18n();
  const { data: editor, error, isLoading, refetch } = useStoryBibleEditor(project);
  const [selected, setSelected] = useState<EntityFocus | null>(focus ?? null);
  const [opened, setOpened] = useState<Open | null>(null);
  const [showAllCharacters, setShowAllCharacters] = useState(false);
  const [showRemoved, setShowRemoved] = useState(false);
  const [query, setQuery] = useState("");
  const unavailable = isNotFoundError(error) || (!editor && !isLoading && !error);
  if (!story) {
    if (unavailable) return null;
    if (error) return <ErrorNotice error={error} operation="load" onRetry={() => void refetch()} />;
    if (!editor) return null;
  }
  // Without the editor, this part's story still shows its entries, read-only.
  const bible = editor?.story_bible ?? story!;
  const open: Open | null = !editor ? null : opened ?? (focus ? { mode: "edit", kind: focus.kind, id: focus.id } : null);
  const close = () => { setOpened(null); if (focus) onFocusClosed?.(); };
  const excluded = editor?.story_bible.excluded_entities ?? [];
  const recurring = castCharacters(bible);
  const needle = query.trim().toLocaleLowerCase();
  const entries = (kind: EntityKind) => ((kind === "characters" && !showAllCharacters ? recurring : bible[kind]) as unknown as Entry[])
    .filter((entry) => !needle || [entry.name, ...(entry.aliases ?? [])].some((name) => name.toLocaleLowerCase().includes(needle)));
  const context: CardContext = { project, bible, editor, partScenes: story?.scenes ?? [], numbers: sceneNumbers(story?.scenes ?? []) };
  const entryOf = (kind: EntityKind, id: string) =>
    (bible[kind] as unknown as Entry[]).find((item) => item.id === id);
  const current = selected && entryOf(selected.kind, selected.id) ? selected : null;
  const imageFor = (kind: EntityKind, id: string) => castImage(project, editor, kind, id);
  const appears = (kind: EntityKind, id: string) => (scene: Scene) =>
    kind === "characters" ? scene.character_ids.includes(id) : kind === "locations" ? scene.location_id === id : false;
  const partScenes = story ? narrativeScenes(story.scenes) : [];
  const hits = current && current.kind !== "props" ? partScenes.filter(appears(current.kind, current.id)).length : 0;
  const pick = (kind: EntityKind, id: string) => {
    setShowRemoved(false);
    setSelected(current?.kind === kind && current.id === id ? null : { kind, id });
  };

  return (
    <section id="story-bible" tabIndex={-1} aria-label={story ? t("Inside your story") : t("Characters, places and props")}
      className="flex min-h-0 min-w-0 flex-1 flex-col focus:outline-none">
      <h2 className="sr-only">{story ? t("Inside your story") : t("CHARACTERS, PLACES & PROPS")}</h2>
      {(error && !isNotFoundError(error)) || editor ? (
        <div className="space-y-3 px-4 pt-4 empty:hidden sm:px-6 studio-desktop:px-5">
          {error && !isNotFoundError(error) && <ErrorNotice error={error} operation="load" onRetry={() => void refetch()} />}
          {editor && <UndoBar project={project} editor={editor} />}
          {editor && <ReferencesToUpdate project={project} editor={editor} />}
          {editor && <DuplicateSuggestions project={project} editor={editor}
            onCompare={(kind, id, into) => setOpened({ mode: "merge", kind, id, into })} />}
        </div>
      ) : null}

      <div className="mt-4 flex min-h-0 flex-1 flex-col border-t border-ink-black/12 studio-desktop:flex-row">
        <aside aria-label={t("Story Bible entries")} className="flex max-h-[26rem] shrink-0 flex-col border-b border-ink-black/12 studio-desktop:max-h-none studio-desktop:w-[16.5rem] studio-desktop:border-b-0 studio-desktop:border-r">
          <div className="shrink-0 px-3 pb-1.5 pt-3">
            <FieldLabel htmlFor="story-bible-search" className="sr-only">{t("Find an entry")}</FieldLabel>
            <div className="relative">
              <Search size={14} aria-hidden="true" className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-muted" />
              <TextField id="story-bible-search" type="search" className="min-h-9 pl-8 text-[0.8125rem]" placeholder={t("Find an entry")} value={query} onChange={(event) => setQuery(event.target.value)} />
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto pb-3">
            {(["characters", "locations", "props"] as const).map((kind) => (
              <div key={kind}>
                <div className="flex items-center justify-between pb-1 pl-4 pr-2 pt-3.5">
                  <h3 className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">
                    {t(TAB_LABELS[kind])} <span className="ml-1 tabular-nums">{entries(kind).length}</span>
                  </h3>
                  {editor && <button type="button" aria-label={t(KIND_LABELS[kind].add)} title={t(KIND_LABELS[kind].add)}
                    onClick={() => setOpened({ mode: "edit", kind })}
                    className="inline-flex h-7 w-7 items-center justify-center text-ink-muted hover:bg-surface-container hover:text-ink-black">
                    <Plus size={15} aria-hidden="true" />
                  </button>}
                </div>
                <ul>
                  {entries(kind).map((entry) => (
                    <EntryRow key={entry.id} kind={kind} entry={entry} context={context}
                      image={imageFor(kind, entry.id)} sceneCount={kind === "props" ? undefined : partScenes.filter(appears(kind, entry.id)).length}
                      active={current?.kind === kind && current.id === entry.id} onPick={() => pick(kind, entry.id)} />
                  ))}
                  {entries(kind).length === 0 && <li className="px-4 py-1.5 font-body text-xs text-ink-muted">{needle ? t("No entry matches.") : t("Nothing here yet.")}</li>}
                </ul>
                {kind === "characters" && recurring.length < bible.characters.length && (
                  <button type="button" onClick={() => setShowAllCharacters(!showAllCharacters)}
                    className="mx-4 mt-1 font-meta text-xs text-ink-soft underline decoration-ink-black/25 underline-offset-4 hover:text-ink-black">
                    {showAllCharacters ? t("Show recurring characters only") : t("Show all source participants")}
                  </button>
                )}
              </div>
            ))}
            {editor && (excluded.length > 0 || showRemoved) && (
              <button type="button" aria-pressed={showRemoved} onClick={() => { setShowRemoved(!showRemoved); setSelected(null); }}
                className={`mx-4 mt-4 font-meta text-xs underline underline-offset-4 ${showRemoved ? "text-ink-black decoration-ink-black" : "text-ink-muted decoration-ink-black/25 hover:text-ink-black"}`}>
                {t("Removed")} <span className="ml-1 tabular-nums">{excluded.length}</span>
              </button>
            )}
          </div>
        </aside>

        <div className="flex min-h-[24rem] min-w-0 flex-1 flex-col bg-surface-container/60 studio-desktop:min-h-0">
          {showRemoved && editor ? (
            <div className="overflow-y-auto px-4 py-5 sm:px-6"><RemovedEntries project={project} editor={editor} /></div>
          ) : story ? <>
            <div className="flex min-h-12 shrink-0 items-center gap-3 px-4 sm:px-5">
              {current ? (
                <span className="inline-flex min-h-[1.875rem] items-center gap-2 bg-ink-black pl-2.5 pr-1 font-meta text-[0.8125rem] font-medium text-pulp-paper">
                  <span aria-hidden="true" className="h-2 w-2 bg-narrator-gold" />
                  {current.kind === "props"
                    ? entryOf(current.kind, current.id)!.name
                    : t("{name} · in {count} of {total} scenes", { name: entryOf(current.kind, current.id)!.name, count: hits, total: partScenes.length })}
                  <button type="button" aria-label={t("Show every scene")} onClick={() => setSelected(null)}
                    className="inline-flex h-6 w-6 items-center justify-center hover:bg-pulp-paper/15"><X size={13} aria-hidden="true" /></button>
                </span>
              ) : (
                <p className="font-meta text-[0.8125rem] text-ink-soft">{t("Every scene, in story order. Pick an entry to see where it appears.")}</p>
              )}
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4 pb-6 sm:px-5 @container">
              <StoryScenes story={story}
                isMatch={current && current.kind !== "props" ? appears(current.kind, current.id) : undefined}
                imageFor={(id) => imageFor("locations", id)} />
            </div>
          </> : !current && (
            <p className="px-5 py-6 font-body text-sm text-ink-muted">{t("Choose an entry to see what the Story Bible holds for it.")}</p>
          )}
        </div>

        {current && !showRemoved && (
          <EntryPanel key={`${current.kind}:${current.id}`} kind={current.kind} entry={entryOf(current.kind, current.id)!} context={context}
            image={imageFor(current.kind, current.id)} onClose={() => setSelected(null)}
            onShow={(id) => pick("characters", id)}
            onEdit={editor ? () => setOpened({ mode: "edit", kind: current.kind, id: current.id }) : undefined} />
        )}
      </div>

      {editor && open?.mode === "edit" && (
        <EntitySheet key={`${open.kind}:${open.id ?? "new"}`} project={project} editor={editor} kind={open.kind} entityId={open.id}
          onClose={close}
          actions={open.id ? (
            <EntryActions editor={editor} kind={open.kind} entityId={open.id}
              onMerge={() => setOpened({ mode: "merge", kind: open.kind, id: open.id! })}
              onRemove={() => setOpened({ mode: "remove", kind: open.kind, id: open.id! })} />
          ) : undefined} />
      )}
      {editor && open?.mode === "merge" && entryOf(open.kind, open.id) && (
        <MergeSheet key={`${open.id}:${open.into ?? ""}`} project={project} editor={editor} kind={open.kind}
          entry={entryOf(open.kind, open.id)!} initialInto={open.into} onClose={close}
          onSwap={(into) => setOpened({ mode: "merge", kind: open.kind, id: into, into: open.id })} />
      )}
      {editor && open?.mode === "remove" && entryOf(open.kind, open.id) && (
        <RemoveSheet project={project} editor={editor} kind={open.kind} entry={entryOf(open.kind, open.id)!} onClose={close} />
      )}
    </section>
  );
}

const CAST_KIND: Record<EntityKind, CastKind> = { characters: "character", locations: "location", props: "prop" };

/** An entry's Cast image, once Cast has drawn one; before Cast runs there is none to show. */
function castImage(project: string, editor: Editor | undefined, kind: EntityKind, id: string) {
  const drawn = editor?.references?.some((ref) => ref.kind === kind && ref.entity_id === id && ref.state_id === null && ref.status !== "missing");
  return drawn ? mainImageUrl(project, CAST_KIND[kind], id) : undefined;
}

function initials(name: string) {
  const words = name.replace(/[^\p{L}\p{N}\s'-]/gu, " ").split(/\s+/).filter(Boolean);
  const meaningful = words.filter((word) => !/^(the|a|an|mr|mrs|ms|dr)$/i.test(word));
  const pickFrom = meaningful.length ? meaningful : words;
  return pickFrom.slice(0, 2).map((word) => word.charAt(0).toLocaleUpperCase()).join("") || "?";
}

/** Shows a Cast image when it loads, otherwise the entry's initials. */
function Thumb({ src, name, wide, className }: { src?: string; name: string; wide?: boolean; className?: string }) {
  const [failed, setFailed] = useState(false);
  return (
    <span aria-hidden="true" className={cn("relative flex shrink-0 items-center justify-center overflow-hidden border border-ink-black/20 bg-[#e9e4cf] font-display text-[0.8125rem] font-black tracking-[-0.02em] text-ink-black",
      wide ? "h-7 w-[2.875rem]" : "h-[2.125rem] w-[2.125rem]", className)}>
      {src && !failed
        ? <img src={src} alt="" loading="lazy" onError={() => setFailed(true)} className="absolute inset-0 h-full w-full object-cover" />
        : initials(name)}
    </span>
  );
}

function entryMeta(kind: EntityKind, entry: Entry) {
  const details = entry as Entry & Partial<Character> & Partial<Location>;
  return kind === "characters" ? [details.age_range, details.gender].filter(known)
    : kind === "locations" ? [readablePhrase(details.time_of_day), readablePhrase(details.mood)].filter(known) : [];
}

/** One entry in the list: who or what it is at a glance, and whether its Cast image needs work. */
function EntryRow({ kind, entry, context, image, sceneCount, active, onPick }: {
  kind: EntityKind; entry: Entry; context: CardContext; image?: string; sceneCount?: number; active: boolean; onPick: () => void;
}) {
  const { t } = useI18n();
  const { editor } = context;
  const stale = referencesToUpdate(editor?.references).filter((ref) => ref.entity_id === entry.id);
  const marker = !stale.length ? null
    : stale.some((ref) => ref.status === "outdated") ? t("Cast image out of date") : t("No Cast image yet");
  const meta = entryMeta(kind, entry).slice(0, kind === "locations" ? 1 : 2);
  if (sceneCount !== undefined) meta.push(t("{count, plural, one {# scene} other {# scenes}}", { count: sceneCount }));
  const subId = `entry-${kind}-${entry.id}-sub`;
  return (
    <li className="relative">
      <button type="button" aria-label={entry.name} aria-describedby={subId} aria-pressed={active} onClick={onPick}
        className={cn("relative flex min-h-12 w-full items-center gap-2.5 px-4 py-1.5 text-left",
          active ? "bg-ink-black text-pulp-paper before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-hero-red" : "hover:bg-surface-container")}>
        <Thumb src={kind === "characters" && image ? portraitUrl(context.project ?? "", entry.id) : image} name={entry.name} wide={kind === "locations"}
          className={active ? "border-narrator-gold bg-narrator-gold" : undefined} />
        <span className="min-w-0">
          <span className="block font-meta text-[0.8125rem] font-semibold leading-[1.2]">{entry.name}</span>
          <span id={subId} className={cn("mt-0.5 block truncate font-body text-[0.6875rem]", active ? "text-bristol/65" : "text-ink-muted")}>{meta.join(" · ")}</span>
        </span>
      </button>
      {(entry.origin === "author" || marker) && (
        <p className="flex flex-wrap gap-x-2 pb-1.5 pl-[3.75rem] pr-3 font-meta text-[0.625rem] uppercase tracking-[0.1em]">
          {entry.origin === "author" && <span className="text-on-gold">{t("Added by you")}</span>}
          {marker && (
            <Link to={{ pathname: "../cast", search: UPDATE_REFERENCES_SEARCH }} relative="path" className="text-hero-red underline">{marker}</Link>
          )}
        </p>
      )}
    </li>
  );
}

/** What the Story Bible holds for one entry, beside the board; its sheet edits it. */
function EntryPanel({ kind, entry, context, image, onClose, onShow, onEdit }: {
  kind: EntityKind; entry: Entry; context: CardContext; image?: string;
  onClose: () => void; onShow: (characterId: string) => void; onEdit?: () => void;
}) {
  const { t } = useI18n();
  const { bible, editor, partScenes, numbers } = context;
  const details = entry as Entry & Partial<Character> & Partial<Location> & Partial<Prop>;
  const cited = editor?.citations[entry.id] ?? [];
  const meta = entryMeta(kind, entry);
  const affect = kind === "characters" ? readablePhrase(details.baseline_affect) : "";
  const names = new Map(bible.characters.map((character) => [character.id, character.name]));
  const relationships = (details.relationships ?? []).flatMap((relationship) => {
    const name = names.get(relationship.character_id);
    return name && relationship.relationship ? [{ id: relationship.character_id, name, relationship: relationship.relationship }] : [];
  });
  // A first appearance may lie in an earlier part; name the part when it isn't numbered here.
  const firstScene = kind === "locations" || !details.first_appearance_scene ? undefined
    : [...bible.scenes, ...partScenes].find((scene) => scene.id === details.first_appearance_scene);
  const firstPart = firstScene && !numbers.has(firstScene.id) ? editor?.parts.find((part) => part.id === firstScene.part_id)?.title : undefined;
  const firstAppears = firstScene && [numbers.get(firstScene.id) ?? firstPart, firstScene.title].filter(Boolean).join(" · ");
  const settings = kind === "locations"
    ? partScenes.filter((scene) => scene.location_id === entry.id && numbers.has(scene.id)).map((scene) => numbers.get(scene.id)!) : [];
  const looks = entry.appearance_states ?? [];
  const kindLabel = { characters: t("Character"), locations: t("Place"), props: t("Prop") }[kind];
  const [imageFailed, setImageFailed] = useState(false);
  return (
    <aside aria-label={entry.name} className="flex max-h-[40rem] shrink-0 flex-col border-t border-ink-black bg-bristol studio-desktop:max-h-none studio-desktop:w-[26rem] studio-desktop:border-l studio-desktop:border-t-0 studio-desktop:shadow-[-18px_0_40px_-24px_rgba(27,28,21,0.45)]">
      <div className="shrink-0 px-6 pb-4 pt-5">
        <div className="flex items-center">
          <p className="font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{[kindLabel, ...meta].join(" · ")}</p>
          <button type="button" aria-label={t("Close")} onClick={onClose}
            className="ml-auto inline-flex h-8 w-8 items-center justify-center text-ink-soft hover:bg-surface-container hover:text-ink-black"><X size={16} aria-hidden="true" /></button>
        </div>
        <h3 className="mt-1.5 break-words font-display text-[1.875rem] font-black uppercase leading-[0.95] tracking-[-0.03em]">{entry.name}</h3>
        {!!entry.aliases?.length && <p className="mt-2 font-meta text-[0.8125rem] text-ink-muted">{t("Also: {names}", { names: entry.aliases.join(", ") })}</p>}
        {entry.origin === "author" && <p className="mt-1 font-meta text-[0.625rem] uppercase tracking-[0.1em] text-on-gold">{t("Added by you")}</p>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {image && !imageFailed && (
          <div className="border-t border-ink-black/10 px-6 py-4">
            <img src={image} alt={t("{name} Cast reference", { name: entry.name })} onError={() => setImageFailed(true)}
              className="block max-h-44 w-full object-contain object-left outline outline-1 outline-ink-black/15" />
          </div>
        )}
        <div className="border-t border-ink-black/10 px-6 py-4">
          <h4 className="mb-2 font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{t("On the page")}</h4>
          {affect && <p className="mb-2 font-body text-sm italic leading-6 text-ink-black/80">{affect}</p>}
          <p className="whitespace-pre-line font-body text-sm leading-[1.6] text-ink-black">{readableAnchor(entry.visual_anchor)}</p>
        </div>
        {relationships.length > 0 && (
          <div className="border-t border-ink-black/10 px-6 py-4">
            <h4 className="mb-2 font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{t("Relationships")}</h4>
            <ul className="space-y-1.5">
              {relationships.map((relationship) => (
                <li key={relationship.id}>
                  <button type="button" onClick={() => onShow(relationship.id)}
                    className="flex min-h-9 w-full items-center justify-between gap-3 border border-ink-black/12 px-2.5 text-left font-meta text-[0.8125rem] hover:border-ink-black">
                    <span className="font-semibold">{relationship.name}</span>
                    <span className="text-ink-muted">{relationship.relationship}</span>
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {looks.length > 0 && (
          <div className="border-t border-ink-black/10 px-6 py-4">
            <h4 className="mb-2 font-meta text-[0.6875rem] font-semibold uppercase tracking-[0.1em] text-ink-muted">{t("Looks")}</h4>
            <ul className="space-y-1">
              {looks.map((look) => <li key={look.id} className="flex items-center gap-2.5 font-meta text-[0.8125rem]"><span aria-hidden="true" className="h-2.5 w-2.5 shrink-0 border border-ink-black bg-bristol" />{look.label}</li>)}
            </ul>
          </div>
        )}
        {(firstAppears || settings.length > 0 || cited.length > 0) && (
          <dl className="space-y-1.5 border-t border-ink-black/10 px-6 py-4 font-body text-[0.8125rem] leading-5">
            {firstAppears && <div className="flex gap-2"><dt className="shrink-0 text-ink-muted">{t("First appears")}</dt><dd className="min-w-0">{firstAppears}</dd></div>}
            {settings.length > 0 && <div className="flex gap-2">
              <dt className="shrink-0 text-ink-muted">{t("{count, plural, one {Scene} other {Scenes}}", { count: settings.length })}</dt>
              <dd className="min-w-0 font-meta tabular-nums">{settings.join(", ")}</dd>
            </div>}
            {cited.length > 0 && <div><dd className="text-ink-muted">{t("Used in {parts}", { parts: cited.join(", ") })}</dd></div>}
          </dl>
        )}
      </div>
      {onEdit && (
        <div className="flex shrink-0 items-center justify-end gap-2 border-t border-ink-black/12 bg-pulp-paper px-6 py-3">
          <Button size="sm" variant="secondary" onClick={onEdit}><Pencil size={13} aria-hidden="true" />{t("Edit details")}</Button>
        </div>
      )}
    </aside>
  );
}

function describeChange(change: StoryBibleChange, t: Translate): string {
  const values = { name: change.name, into: change.into ?? "", look: change.look ?? "" };
  switch (change.action) {
    case "edit": return t("Edited {name}", values);
    case "add": return t("Added {name}", values);
    case "remove": return t("Removed {name}", values);
    case "merge": return t("Merged {name} into {into}", values);
    case "add_look": return t("Added the look {look} to {name}", values);
    case "edit_look": return t("Edited the look {look} of {name}", values);
    case "remove_look": return t("Removed the look {look} from {name}", values);
    case "restore": return t("Brought back {name}", values);
  }
}

function UndoBar({ project, editor }: { project: string; editor: Editor }) {
  const { t } = useI18n();
  const undo = useUndoEdit();
  if (!editor.undo) return null;
  const { change, blocked } = editor.undo;
  return (
    <div role="status" className="flex flex-wrap items-center gap-x-3 gap-y-1">
      <p className="min-w-0 font-meta text-[0.8125rem] text-ink-soft">
        <span className="mr-1.5 text-ink-muted">{t("Last change")}:</span>
        {describeChange(change, t)}
        {blocked && <span className="ml-2 text-xs text-ink-muted">{t("An adapted part now uses what this change added, so it can't be undone.")}</span>}
      </p>
      {undo.error && <ErrorNotice error={undo.error} operation="save" />}
      <Button size="xs" variant="outline" className="border-transparent" disabled={!!blocked || undo.isPending}
        onClick={() => undo.mutate({ project, revision: editor.revision })}>
        <Undo2 size={13} aria-hidden="true" />{undo.isPending ? t("Undoing…") : t("Undo")}
      </Button>
    </div>
  );
}

/** Images the author's edits left missing or out of date, with the way to make them. */
function ReferencesToUpdate({ project, editor }: { project: string; editor: Editor }) {
  const { t } = useI18n();
  const navigate = useNavigate();
  // Queued or running work may already be making them; is_running covers both.
  const busy = !!useProjectStatus(project).data?.is_running;
  const pending = referencesToUpdate(editor.references);
  if (!pending.length) return null;
  const bible = editor.story_bible;
  const entities = new Map<string, Entry>(
    ([...bible.characters, ...bible.locations, ...bible.props] as unknown as Entry[]).map((entity) => [entity.id, entity]),
  );
  return (
    <section aria-label={t("Cast images to update")} className="flex flex-wrap items-center gap-x-4 gap-y-2 border border-ink-black bg-narrator-gold/35 px-3.5 py-2">
      <div className="min-w-0 flex-[1_1_16rem]">
        <h3 className="inline font-meta text-[0.8125rem] font-semibold">
          {t("{count, plural, one {# Cast image to update} other {# Cast images to update}}", { count: pending.length })}
        </h3>
        <ul className="inline">
          {pending.map((ref) => {
            const entity = entities.get(ref.entity_id);
            const look = ref.state_id ? entity?.appearance_states?.find((state) => state.id === ref.state_id)?.label ?? ref.state_id : null;
            return (
              <li key={`${ref.entity_id}:${ref.state_id ?? ""}`} className="ml-3 inline font-body text-[0.8125rem]">
                <span className="font-semibold">{entity?.name ?? ref.entity_id}</span>
                {look && <span className="text-ink-soft"> · {look}</span>}
                <span className="ml-1.5 text-xs text-ink-muted">({ref.status === "missing" ? t("New, no image yet") : t("Changed since its image")})</span>
              </li>
            );
          })}
        </ul>
        {busy && <p className="mt-0.5 font-body text-xs text-ink-muted">{t("Work is running on this project. Update these once it finishes.")}</p>}
      </div>
      <Button size="sm" variant="secondary" className="shrink-0" disabled={busy}
        title={t("Cast shows the cost before generating anything.")}
        onClick={() => navigate({ pathname: "../cast", search: UPDATE_REFERENCES_SEARCH }, { relative: "path" })}>
        {t("Update in Cast")}<ArrowRight size={14} aria-hidden="true" />
      </Button>
    </section>
  );
}

/** Per-viewer convenience: pairs this author said aren't duplicates. */
function useDismissedPairs(project: string): [Set<string>, (key: string) => void] {
  const storageKey = `scenewright:story-bible:not-duplicates:${splitProjectKey(project).id}`;
  const [dismissed, setDismissed] = useState<Set<string>>(() => {
    try { return new Set(JSON.parse(localStorage.getItem(storageKey) ?? "[]") as string[]); } catch { return new Set(); }
  });
  return [dismissed, (key) => {
    const next = new Set(dismissed).add(key);
    setDismissed(next);
    try { localStorage.setItem(storageKey, JSON.stringify([...next])); } catch { /* still hidden for this visit */ }
  }];
}

function DuplicateSuggestions({ project, editor, onCompare }: {
  project: string; editor: Editor; onCompare: (kind: EntityKind, id: string, into: string) => void;
}) {
  const { t } = useI18n();
  const [dismissed, dismiss] = useDismissedPairs(project);
  const pairs = (editor.possible_duplicates ?? []).filter((pair) => !dismissed.has(`${pair.kind}:${pair.ids.join("+")}`));
  if (!pairs.length) return null;
  const nameOf = (kind: EntityKind, id: string) =>
    (editor.story_bible[kind] as unknown as Entry[]).find((item) => item.id === id)?.name ?? id;
  return (
    <section aria-label={t("Possible duplicates")} className="space-y-2">
      <h3 className="font-meta text-xs font-bold uppercase tracking-[0.12em] text-ink-muted">{t("Possible duplicates")}</h3>
      <ul className="space-y-2">
        {pairs.map((pair) => {
          // The cited entry stays; otherwise fold the shorter name into the fuller one.
          const [a, b] = pair.ids;
          const source = editor.citations[a]?.length ? b : editor.citations[b]?.length ? a
            : nameOf(pair.kind, a).length <= nameOf(pair.kind, b).length ? a : b;
          const into = source === a ? b : a;
          return (
            <li key={`${pair.kind}:${a}+${b}`} className="flex flex-wrap items-center gap-3 border-[2px] border-dashed border-ink-black/20 px-4 py-2">
              <span className="min-w-0 flex-1 font-body text-sm">
                {t("{first} and {second} may be the same {kind}.", { first: nameOf(pair.kind, a), second: nameOf(pair.kind, b), kind: t(KIND_LABELS[pair.kind].one) })}
              </span>
              <Button size="xs" variant="outline" onClick={() => onCompare(pair.kind, source, into)}>{t("Compare")}</Button>
              <Button size="xs" variant="outline" onClick={() => dismiss(`${pair.kind}:${a}+${b}`)}>{t("Not the same")}</Button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Merge and remove live inside an entry, behind a clear explanation, never on the list. */
function EntryActions({ editor, kind, entityId, onMerge, onRemove }: {
  editor: Editor; kind: EntityKind; entityId: string; onMerge: () => void; onRemove: () => void;
}) {
  const { t } = useI18n();
  const cited = editor.citations[entityId] ?? [];
  const alone = (editor.story_bible[kind] as unknown[]).length < 2;
  return (
    <section aria-label={t("Merge or remove")} className="space-y-3 border-t-2 border-ink-black/10 pt-5">
      <h3 className="font-meta text-xs font-bold uppercase tracking-[0.12em] text-ink-muted">{t("Merge or remove")}</h3>
      {cited.length > 0 ? (
        <p className="font-body text-sm text-ink-muted">
          {t("{parts} already uses this entry, so it can only be edited. Restart those parts' adaptation to merge or remove it.", { parts: cited.join(", ") })}
        </p>
      ) : (
        <p className="font-body text-sm text-ink-muted">{t("You'll see exactly what changes before anything is saved, and you can undo it afterwards.")}</p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button size="sm" variant="outline" onClick={onMerge} disabled={cited.length > 0 || alone}>{t("Merge into another entry…")}</Button>
        <Button size="sm" variant="outline" onClick={onRemove} disabled={cited.length > 0}
          className="text-hero-red">{t("Remove from the story…")}</Button>
      </div>
    </section>
  );
}

function ImpactSummary({ impact, kind, name, into }: { impact: EditImpact; kind: EntityKind; name: string; into?: string }) {
  const { t } = useI18n();
  const merge = impact.action === "merge";
  const lines: ReactNode[] = [];
  const scenes = impact.scenes.map((scene) => scene.title).join(", ");
  if (merge) {
    if (impact.aliases.length) lines.push(t("{names} become other names for {target}.", { names: impact.aliases.join(", "), target: into ?? "" }));
    if (impact.scenes.length) lines.push(t("{count, plural, one {# scene moves} other {# scenes move}} to {target}: {scenes}", { count: impact.scenes.length, target: into ?? "", scenes }));
    if (impact.looks.length) lines.push(t("Its looks move to {target}: {looks}", { target: into ?? "", looks: impact.looks.join(", ") }));
    if (impact.relationships) lines.push(t("{count, plural, one {# relationship moves} other {# relationships move}} to {target}.", { count: impact.relationships, target: into ?? "" }));
    lines.push(t("{target}'s description and Cast images stay as they are; {name}'s description is set aside.", { target: into ?? "", name }));
  } else {
    if (impact.scenes.length) lines.push(kind === "characters"
      ? t("{name} leaves {count, plural, one {# scene} other {# scenes}}: {scenes}", { name, count: impact.scenes.length, scenes })
      : t("{name} first appears in: {scenes}", { name, scenes }));
    if (impact.looks.length) lines.push(t("Its looks go with it: {looks}", { looks: impact.looks.join(", ") }));
    if (impact.relationships) lines.push(t("{count, plural, one {# relationship is} other {# relationships are}} set aside.", { count: impact.relationships }));
    lines.push(t("Later extractions won't add {name} back.", { name }));
  }
  if (impact.cast_images) lines.push(merge
    ? t("{count, plural, one {# Cast image} other {# Cast images}} of {name} stop being used. Undo brings them back.", { count: impact.cast_images, name })
    : t("{count, plural, one {# Cast image stops} other {# Cast images stop}} being used. Bringing {name} back restores them.", { count: impact.cast_images, name }));
  if (impact.new_references) lines.push(impact.reopens_cast
    ? t("Cast needs {count, plural, one {# new reference image} other {# new reference images}} and reopens for your review.", { count: impact.new_references })
    : t("Cast will need {count, plural, one {# new reference image} other {# new reference images}}.", { count: impact.new_references }));
  return (
    <div className="space-y-2">
      <h3 className="font-meta text-xs font-bold uppercase tracking-[0.12em] text-ink-muted">{t("What changes")}</h3>
      <ul className="list-disc space-y-1.5 pl-5 font-body text-sm leading-6">
        {lines.map((line, index) => <li key={index}>{line}</li>)}
      </ul>
    </div>
  );
}

function ImpactState({ impact, isLoading, error, children }: {
  impact?: EditImpact; isLoading: boolean; error: Error | null; children: (impact: EditImpact) => ReactNode;
}) {
  const { t } = useI18n();
  if (error) return <ErrorNotice error={error} operation="load" />;
  if (isLoading || !impact) return <p className="font-body text-sm text-ink-muted">{t("Checking what this changes…")}</p>;
  if (impact.blocked) return <p role="alert" className="border-l-4 border-hero-red bg-surface-container px-4 py-3 font-body text-sm">{impact.blocked}</p>;
  return <>{children(impact)}</>;
}

function EntryCard({ label, entry, tone }: { label: string; entry?: Entry; tone: "fold" | "keep" }) {
  const { t } = useI18n();
  return (
    <div className={`min-w-0 flex-1 border-[2px] p-4 ${tone === "keep" ? "border-ink-black bg-pulp-paper shadow-paper-sm" : "border-dashed border-ink-black/30"}`}>
      <p className="font-meta text-[0.6rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{label}</p>
      {entry ? <>
        <p className="mt-1 font-display text-lg font-bold">{entry.name}</p>
        {!!entry.aliases?.length && <p className="font-body text-xs text-ink-muted">{t("Also: {names}", { names: entry.aliases.join(", ") })}</p>}
        <p className="mt-2 line-clamp-4 font-body text-sm text-ink-muted">{readableAnchor(entry.visual_anchor)}</p>
        {!!entry.appearance_states?.length && (
          <p className="mt-2 font-body text-xs text-ink-muted">{t("Looks: {looks}", { looks: entry.appearance_states.map((state) => state.label).join(", ") })}</p>
        )}
      </> : <p className="mt-1 font-body text-sm text-ink-muted">{t("Choose an entry below.")}</p>}
    </div>
  );
}

function MergeSheet({ project, editor, kind, entry, initialInto, onClose, onSwap }: {
  project: string; editor: Editor; kind: EntityKind; entry: Entry; initialInto?: string;
  onClose: () => void; onSwap: (into: string) => void;
}) {
  const { t } = useI18n();
  const merge = useMergeEntity();
  const [into, setInto] = useState<string | undefined>(initialInto);
  const [query, setQuery] = useState("");
  const others = useMemo(() => (editor.story_bible[kind] as unknown as Entry[]).filter((item) => item.id !== entry.id), [editor, kind, entry.id]);
  const needle = query.trim().toLocaleLowerCase();
  const matches = others.filter((item) => !needle
    || [item.name, ...(item.aliases ?? [])].some((name) => name.toLocaleLowerCase().includes(needle)));
  const target = others.find((item) => item.id === into);
  const impact = useEditImpact(project, kind, entry.id, "merge", into, editor.revision);
  const canSwap = !!target && !(editor.citations[target.id]?.length);
  const ready = !!target && !!impact.data && !impact.data.blocked && !merge.isPending;
  return (
    <Sheet open wide title={t("Merge {name}", { name: entry.name })} onClose={onClose}
      description={t("Use this when extraction found the same {kind} twice under different names. One entry stays; the other folds into it.", { kind: t(KIND_LABELS[kind].one) })}
      footer={<>
        {merge.error && <ErrorNotice error={merge.error} operation="save" />}
        <Button variant="outline" onClick={onClose} disabled={merge.isPending}>{t("Cancel")}</Button>
        <Button disabled={!ready} onClick={() => target && merge.mutate(
          { project, kind, id: entry.id, into: target.id, revision: editor.revision }, { onSuccess: onClose },
        )}>{merge.isPending ? t("Merging…") : target ? t("Merge into {target}", { target: target.name }) : t("Merge")}</Button>
      </>}>
      <div className="space-y-6">
        <div className="flex flex-col items-stretch gap-3 md:flex-row md:items-center">
          <EntryCard label={t("Folds in")} entry={entry} tone="fold" />
          <ArrowRight size={24} aria-hidden="true" className="mx-auto shrink-0 rotate-90 text-ink-muted md:rotate-0" />
          <EntryCard label={t("Stays")} entry={target} tone="keep" />
        </div>
        {canSwap && (
          <Button size="xs" variant="outline" onClick={() => onSwap(target!.id)}>{t("Keep {name} instead", { name: entry.name })}</Button>
        )}
        {!initialInto && (
          <fieldset className="space-y-3">
            <legend className="ui-field-label">{t("Which entry stays?")}</legend>
            <div className="relative max-w-md">
              <FieldLabel htmlFor="merge-search" className="sr-only">{t("Find an entry")}</FieldLabel>
              <Search size={16} aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
              <TextField id="merge-search" className="pl-9" placeholder={t("Find an entry")} value={query} onChange={(event) => setQuery(event.target.value)} />
            </div>
            <ul className="max-h-56 space-y-1 overflow-y-auto">
              {matches.map((item) => (
                <li key={item.id}>
                  <label className="flex min-h-11 items-center gap-3 font-body text-sm">
                    <input type="radio" name="merge-into" className="h-5 w-5" checked={into === item.id} onChange={() => setInto(item.id)} />
                    <span className="font-bold">{item.name}</span>
                    {!!item.aliases?.length && <span className="truncate text-xs text-ink-muted">{item.aliases.join(", ")}</span>}
                  </label>
                </li>
              ))}
              {matches.length === 0 && <li className="py-2 font-body text-sm text-ink-muted">{t("No entry matches.")}</li>}
            </ul>
          </fieldset>
        )}
        {target && (
          <ImpactState impact={impact.data} isLoading={impact.isLoading} error={impact.error}>
            {(data) => <ImpactSummary impact={data} kind={kind} name={entry.name} into={target.name} />}
          </ImpactState>
        )}
      </div>
    </Sheet>
  );
}

function RemoveSheet({ project, editor, kind, entry, onClose }: {
  project: string; editor: Editor; kind: EntityKind; entry: Entry; onClose: () => void;
}) {
  const { t } = useI18n();
  const remove = useRemoveEntity();
  const impact = useEditImpact(project, kind, entry.id, "remove", undefined, editor.revision);
  const ready = !!impact.data && !impact.data.blocked && !remove.isPending;
  return (
    <Sheet open title={t("Remove {name}?", { name: entry.name })} onClose={onClose}
      description={t("Use this for someone or something that isn't really in the story. Nothing is deleted: you can bring it back from Removed.")}
      footer={<>
        {remove.error && <ErrorNotice error={remove.error} operation="delete" />}
        <Button variant="outline" onClick={onClose} disabled={remove.isPending}>{t("Cancel")}</Button>
        <Button disabled={!ready} onClick={() => remove.mutate(
          { project, kind, id: entry.id, revision: editor.revision }, { onSuccess: onClose },
        )}>{remove.isPending ? t("Removing…") : t("Remove {name}", { name: entry.name })}</Button>
      </>}>
      <ImpactState impact={impact.data} isLoading={impact.isLoading} error={impact.error}>
        {(data) => <ImpactSummary impact={data} kind={kind} name={entry.name} />}
      </ImpactState>
    </Sheet>
  );
}

function RemovedEntries({ project, editor }: { project: string; editor: Editor }) {
  const { t } = useI18n();
  const restore = useRestoreExcluded();
  const excluded = editor.story_bible.excluded_entities ?? [];
  const kinds: Record<ExcludedEntity["kind"], string> = { character: t("Character"), location: t("Place"), prop: t("Prop") };
  return (
    <div className="space-y-3">
      <p className="font-body text-sm text-ink-muted">{t("Later extractions skip these names. Bring one back to return it to the scenes it left, with its details, looks and Cast images.")}</p>
      {restore.error && <ErrorNotice error={restore.error} operation="save" />}
      <ul className="divide-y-[2px] divide-ink-black/10 border-y-[2px] border-ink-black/10">
        {excluded.map((entry) => (
          <li key={`${entry.kind}:${entry.name}`} className="flex flex-wrap items-center gap-4 py-3">
            <span className="min-w-0 flex-1 font-body text-sm">
              <span className="font-bold">{entry.name}</span>
              <span className="ml-2 font-meta text-xs text-ink-muted">{kinds[entry.kind]}</span>
              {entry.aliases.length > 0 && <span className="ml-2 text-ink-muted">{t("Also: {names}", { names: entry.aliases.join(", ") })}</span>}
              {!entry.removed && <span className="mt-0.5 block text-xs text-ink-muted">{t("Only the name was kept; extraction can find it again in new parts.")}</span>}
            </span>
            <Button size="xs" variant="outline" disabled={restore.isPending}
              onClick={() => restore.mutate({ project, kind: EXCLUDED_KIND[entry.kind], name: entry.name, revision: editor.revision })}>
              {entry.removed ? t("Bring back") : t("Allow again")}
            </Button>
          </li>
        ))}
        {excluded.length === 0 && <li className="py-6 font-body text-sm text-ink-muted">{t("Nothing removed.")}</li>}
      </ul>
    </div>
  );
}

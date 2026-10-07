import { ErrorNotice } from "../composites/ErrorNotice";
import { useMemo, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowRight, ChevronRight, Search, Undo2 } from "lucide-react";
import { useI18n } from "../../i18n";
import { RoomTabs } from "../composites/RoomTabs";
import { SectionHeader } from "../composites/SectionHeader";
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
import {
  useEditImpact, useMergeEntity, useRemoveEntity, useRestoreExcluded, useStoryBibleEditor, useUndoEdit,
} from "../../api/seriesQueries";
import type { EditImpact, EntityKind, StoryBibleChange, StoryBibleEditor as Editor } from "../../api/storyBible";
import type { Character, ExcludedEntity, Location, Prop, Scene, StoryBible } from "../../types/api";

type Tab = "scenes" | EntityKind | "removed";
type Entry = {
  id: string; name: string; aliases?: string[]; origin?: string; visual_anchor: string;
  appearance_states?: { id: string; label: string }[];
};
type Translate = ReturnType<typeof useI18n>["t"];

const TAB_LABELS: Record<Tab, string> = { scenes: "Scenes", characters: "Characters", locations: "Places", props: "Props", removed: "Removed" };
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
  bible: StoryBible;
  editor?: Editor;
  /** This part's scenes, numbered in reading order. */
  partScenes: Scene[];
  numbers: Map<string, string>;
}

/**
 * The story at a glance and the author's view of the shared Story Bible:
 * this part's scenes are read-only; every part reads the entries.
 */
export function StoryBibleEditor({ project, story, focus, onFocusClosed }: Props) {
  const { t } = useI18n();
  const { data: editor, error, isLoading, refetch } = useStoryBibleEditor(project);
  const [tab, setTab] = useState<Tab>(focus?.kind ?? (story ? "scenes" : "characters"));
  const [opened, setOpened] = useState<Open | null>(null);
  const [showAllCharacters, setShowAllCharacters] = useState(false);
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
  const entries = (kind: EntityKind) => (kind === "characters" && !showAllCharacters
    ? recurring : bible[kind]) as unknown as Entry[];
  const sceneCount = story ? narrativeScenes(story.scenes).length : 0;
  const tabs = ((story ? ["scenes"] : []).concat(["characters", "locations", "props"]) as Tab[]).map((key) => ({
    key, label: t(TAB_LABELS[key]), count: key === "scenes" ? sceneCount : entries(key as EntityKind).length,
    active: tab === key, onClick: () => setTab(key),
  }));
  const entityTab = tab === "scenes" || tab === "removed" ? null : tab;
  const context: CardContext = { bible, editor, partScenes: story?.scenes ?? [], numbers: sceneNumbers(story?.scenes ?? []) };
  const entryOf = (kind: EntityKind, id: string) =>
    (bible[kind] as unknown as Entry[]).find((item) => item.id === id);

  return (
    <section id="story-bible" tabIndex={-1} className="min-w-0 space-y-6" aria-label={story ? t("Inside your story") : t("Characters, places and props")}>
      <SectionHeader
        kicker={t("STORY BIBLE")}
        title={story ? t("Inside your story") : t("CHARACTERS, PLACES & PROPS")}
        description={story
          ? t("Scenes come from this part and are read-only; shape the adaptation in the brief above. Every part shares the characters, places and props: open one to fix what extraction got wrong, merge a duplicate or remove it.")
          : t("Every part shares these entries. Open one to fix what extraction got wrong, merge a duplicate or remove it. You can undo your latest change.")}
        actions={editor && entityTab && <Button size="sm" variant="outline" onClick={() => setOpened({ mode: "edit", kind: entityTab })}>{t(KIND_LABELS[entityTab].add)}</Button>}
      />
      {error && !isNotFoundError(error) && <ErrorNotice error={error} operation="load" onRetry={() => void refetch()} />}
      {editor && <UndoBar project={project} editor={editor} />}
      {editor && <ReferencesToUpdate project={project} editor={editor} />}
      {editor && <DuplicateSuggestions project={project} editor={editor}
        onCompare={(kind, id, into) => setOpened({ mode: "merge", kind, id, into })} />}
      <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
        <RoomTabs ariaLabel={t("Story Bible sections")} className="max-w-full" tabs={tabs} />
        {editor && (excluded.length > 0 || tab === "removed") && (
          <button type="button" aria-pressed={tab === "removed"} onClick={() => setTab(tab === "removed" ? "characters" : "removed")}
            className={`min-h-11 font-meta text-xs uppercase tracking-[0.1em] underline decoration-ink-black/30 underline-offset-4 hover:decoration-ink-black ${tab === "removed" ? "text-ink-black decoration-ink-black" : "text-ink-muted"}`}>
            {t("Removed")} <span className="ml-1 tabular-nums">{excluded.length}</span>
          </button>
        )}
      </div>
      {tab === "characters" && recurring.length < bible.characters.length && (
        <Button size="sm" variant="outline" onClick={() => setShowAllCharacters(!showAllCharacters)}>
          {showAllCharacters ? t("Show recurring characters only") : t("Show all source participants")}
        </Button>
      )}
      {tab === "scenes" && story ? (
        <StoryScenes story={story} />
      ) : tab === "removed" && editor ? (
        <RemovedEntries project={project} editor={editor} />
      ) : entityTab && (
        <ul className="grid gap-x-8 md:grid-cols-2">
          {entries(entityTab).map((entry) => (
            <EntityCard key={entry.id} kind={entityTab} entry={entry} context={context}
              onOpen={editor ? () => setOpened({ mode: "edit", kind: entityTab, id: entry.id }) : undefined} />
          ))}
          {entries(entityTab).length === 0 && <li className="py-6 font-body text-sm text-ink-muted">{t("Nothing here yet.")}</li>}
        </ul>
      )}
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
    <div role="status" className="flex flex-wrap items-center gap-x-4 gap-y-2 border-l-4 border-narrator-gold bg-surface-container px-4 py-3">
      <p className="min-w-0 flex-1 font-body text-sm">
        <span className="mr-2 font-meta text-[0.65rem] font-bold uppercase tracking-[0.12em] text-ink-muted">{t("Last change")}</span>
        {describeChange(change, t)}
        {blocked && <span className="mt-1 block text-xs text-ink-muted">{t("An adapted part now uses what this change added, so it can't be undone.")}</span>}
      </p>
      {undo.error && <ErrorNotice error={undo.error} operation="save" />}
      <Button size="sm" variant="outline" disabled={!!blocked || undo.isPending}
        onClick={() => undo.mutate({ project, revision: editor.revision })}>
        <Undo2 size={16} aria-hidden="true" className="mr-2 inline" />{undo.isPending ? t("Undoing…") : t("Undo")}
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
    <section aria-label={t("Cast images to update")} className="space-y-3 border-l-4 border-hero-red bg-surface-container px-4 py-4">
      <div className="flex flex-wrap items-start gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1">
          <h3 className="font-meta text-xs font-bold uppercase tracking-[0.12em]">
            {t("{count, plural, one {# Cast image to update} other {# Cast images to update}}", { count: pending.length })}
          </h3>
          <p className="mt-1 font-body text-sm text-ink-muted">
            {t("Your edits changed or added these entries. Pages draw them from Cast images, so update the images before drawing.")}
          </p>
        </div>
        <Button size="sm" className="shrink-0" disabled={busy}
          onClick={() => navigate({ pathname: "../cast", search: UPDATE_REFERENCES_SEARCH }, { relative: "path" })}>
          {t("Update in Cast")}<ArrowRight size={16} aria-hidden="true" className="ml-2 inline" />
        </Button>
      </div>
      <ul className="space-y-1 font-body text-sm">
        {pending.map((ref) => {
          const entity = entities.get(ref.entity_id);
          const look = ref.state_id ? entity?.appearance_states?.find((state) => state.id === ref.state_id)?.label ?? ref.state_id : null;
          return (
            <li key={`${ref.entity_id}:${ref.state_id ?? ""}`}>
              <span className="font-bold">{entity?.name ?? ref.entity_id}</span>
              {look && <span className="text-ink-muted"> · {look}</span>}
              <span className="ml-2 font-meta text-[0.65rem] uppercase tracking-[0.12em] text-ink-muted">
                {ref.status === "missing" ? t("New, no image yet") : t("Changed since its image")}
              </span>
            </li>
          );
        })}
      </ul>
      <p className="font-body text-xs text-ink-muted">
        {busy ? t("Work is running on this project. Update these once it finishes.") : t("Cast shows the cost before generating anything.")}
      </p>
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

/** Who or what an entry is, at a glance; the whole card opens its editor when one is available. */
function EntityCard({ kind, entry, context, onOpen }: {
  kind: EntityKind; entry: Entry; context: CardContext; onOpen?: () => void;
}) {
  const { t } = useI18n();
  const { bible, editor, partScenes, numbers } = context;
  const details = entry as Entry & Partial<Character> & Partial<Location> & Partial<Prop>;
  const cited = editor?.citations[entry.id] ?? [];
  const stale = referencesToUpdate(editor?.references).filter((ref) => ref.entity_id === entry.id);
  const marker = !stale.length ? null
    : stale.some((ref) => ref.status === "outdated") ? t("Cast image out of date") : t("No Cast image yet");
  const meta = kind === "characters" ? [details.age_range, details.gender].filter(known)
    : kind === "locations" ? [readablePhrase(details.time_of_day), readablePhrase(details.mood)].filter(known) : [];
  const affect = kind === "characters" ? readablePhrase(details.baseline_affect) : "";
  const names = new Map(bible.characters.map((character) => [character.id, character.name]));
  const relationships = (details.relationships ?? []).flatMap((relationship) => {
    const name = names.get(relationship.character_id);
    return name && relationship.relationship ? [{ name, relationship: relationship.relationship }] : [];
  });
  // A first appearance may lie in an earlier part; name the part when it isn't numbered here.
  const firstScene = kind === "locations" || !details.first_appearance_scene ? undefined
    : [...bible.scenes, ...partScenes].find((scene) => scene.id === details.first_appearance_scene);
  const firstPart = firstScene && !numbers.has(firstScene.id) ? editor?.parts.find((part) => part.id === firstScene.part_id)?.title : undefined;
  const firstAppears = firstScene && [numbers.get(firstScene.id) ?? firstPart, firstScene.title].filter(Boolean).join(" · ");
  const settings = kind === "locations"
    ? partScenes.filter((scene) => scene.location_id === entry.id && numbers.has(scene.id)).map((scene) => numbers.get(scene.id)!) : [];
  return (
    <li className={`group relative flex min-w-0 items-start gap-3 border-b border-ink-black/15 px-3 py-6 ${onOpen ? "hover:bg-surface-container/60" : ""}`}>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <h3 className="font-display text-xl font-bold leading-tight">
            {onOpen ? (
              <button type="button" onClick={onOpen}
                className="text-left underline-offset-4 after:absolute after:inset-0 hover:underline focus-visible:outline-none focus-visible:after:outline focus-visible:after:outline-2 focus-visible:after:outline-ink-black">
                {entry.name}
              </button>
            ) : entry.name}
          </h3>
          {entry.origin === "author" && <span className="font-meta text-[0.6rem] uppercase tracking-[0.12em] text-narrator-gold">{t("Added by you")}</span>}
          {marker && (
            <Link to={{ pathname: "../cast", search: UPDATE_REFERENCES_SEARCH }} relative="path"
              className="relative z-10 font-meta text-[0.6rem] uppercase tracking-[0.12em] text-hero-red underline">
              {marker}
            </Link>
          )}
        </div>
        {meta.length > 0 && <p className="mt-1.5 font-meta text-xs text-ink-muted">{meta.join(" · ")}</p>}
        {!!entry.aliases?.length && <p className="mt-1 font-body text-xs text-ink-muted">{t("Also: {names}", { names: entry.aliases.join(", ") })}</p>}
        {affect && <p className="mt-3 font-body text-sm italic leading-6 text-ink-black/80">{affect}</p>}
        <p className="mt-3 whitespace-pre-line font-body text-sm leading-7 text-ink-black">{readableAnchor(entry.visual_anchor)}</p>
        {(relationships.length > 0 || firstAppears || settings.length > 0) && (
          <dl className="mt-4 space-y-1.5 text-xs leading-5 text-ink-muted">
            {relationships.map((relationship) => (
              <div key={relationship.name} className="flex flex-wrap gap-x-1.5">
                <dt className="font-bold text-ink-black">{relationship.name}</dt>
                <dd className="min-w-0">· {relationship.relationship}</dd>
              </div>
            ))}
            {firstAppears && (
              <div className="flex gap-1.5">
                <dt className="shrink-0">{t("First appears")}</dt>
                <dd className="min-w-0 text-ink-black">{firstAppears}</dd>
              </div>
            )}
            {settings.length > 0 && (
              <div className="flex gap-1.5">
                <dt className="shrink-0">{t("{count, plural, one {Scene} other {Scenes}}", { count: settings.length })}</dt>
                <dd className="min-w-0 font-meta tabular-nums text-ink-black">{settings.join(", ")}</dd>
              </div>
            )}
          </dl>
        )}
        {cited.length > 0 && <p className="mt-1.5 font-body text-xs text-ink-muted">{t("Used in {parts}", { parts: cited.join(", ") })}</p>}
      </div>
      {onOpen && <ChevronRight size={20} aria-hidden="true" className="mt-1 shrink-0 text-ink-muted transition-transform group-hover:translate-x-0.5 motion-reduce:transition-none" />}
    </li>
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

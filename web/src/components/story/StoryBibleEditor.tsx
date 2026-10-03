import { useState } from "react";
import { Link } from "react-router-dom";
import { useI18n } from "../../i18n";
import { RoomTabs } from "../composites/RoomTabs";
import { SectionHeader } from "../composites/SectionHeader";
import { ConfirmModal } from "../composites/ConfirmModal";
import { Sheet } from "../composites/Sheet";
import { Button } from "../ui/Button";
import { FieldLabel, SelectField } from "../ui/Field";
import { EntitySheet } from "./EntitySheet";
import { KIND_LABELS } from "./entityKinds";
import { isNotFoundError } from "../../api/client";
import { castCharacters } from "../../lib/castRoster";
import { useMergeEntity, useRemoveEntity, useRestoreExcluded, useStoryBibleEditor } from "../../api/seriesQueries";
import type { EntityKind, StoryBibleEditor as Editor } from "../../api/storyBible";
import type { ExcludedEntity } from "../../types/api";

type Tab = EntityKind | "removed";
type Entry = { id: string; name: string; aliases?: string[]; origin?: string; visual_anchor: string };

const TAB_LABELS: Record<Tab, string> = { characters: "Characters", locations: "Places", props: "Props", removed: "Removed names" };
const EXCLUDED_KIND: Record<ExcludedEntity["kind"], EntityKind> = { character: "characters", location: "locations", prop: "props" };

export interface EntityFocus { kind: EntityKind; id: string }

interface Props {
  project: string;
  /** Open one entity's editor, e.g. from Cast's "Edit details". */
  focus?: EntityFocus | null;
  onFocusClosed?: () => void;
}

/** The author's view of the shared Story Bible: every part reads these entries. */
export function StoryBibleEditor({ project, focus, onFocusClosed }: Props) {
  const { t } = useI18n();
  const { data: editor, error, isLoading } = useStoryBibleEditor(project);
  const [tab, setTab] = useState<Tab>(focus?.kind ?? "characters");
  const [sheet, setSheet] = useState<{ kind: EntityKind; id?: string } | null>(null);
  const [showAllCharacters, setShowAllCharacters] = useState(false);
  const [merging, setMerging] = useState<{ kind: EntityKind; entry: Entry } | null>(null);
  const [removing, setRemoving] = useState<{ kind: EntityKind; entry: Entry } | null>(null);
  const remove = useRemoveEntity();
  const restore = useRestoreExcluded();
  if (isNotFoundError(error) || (!editor && !isLoading && !error)) return null;
  if (error) return <p role="alert" className="font-body text-sm text-hero-red">{error.message}</p>;
  if (!editor) return null;
  const open = sheet ?? (focus ? { kind: focus.kind, id: focus.id } : null);
  const excluded = editor.story_bible.excluded_entities ?? [];
  const recurring = castCharacters(editor.story_bible);
  const entries = (kind: EntityKind) => (kind === "characters" && !showAllCharacters
    ? recurring : editor.story_bible[kind]) as unknown as Entry[];
  const tabs = (["characters", "locations", "props", "removed"] as Tab[]).map((key) => ({
    key, label: t(TAB_LABELS[key]), count: key === "removed" ? excluded.length : entries(key).length,
    active: tab === key, onClick: () => setTab(key),
  }));

  return (
    <section id="story-bible" className="space-y-6" aria-label={t("Characters, places and props")}>
      <SectionHeader
        variant="underline"
        title={t("CHARACTERS, PLACES & PROPS")}
        description={t("Every part shares these entries. Edit what extraction got wrong, add what it missed, and merge duplicates.")}
        actions={tab !== "removed" && <Button size="sm" variant="outline" onClick={() => setSheet({ kind: tab })}>{t(KIND_LABELS[tab].add)}</Button>}
      />
      <RoomTabs ariaLabel={t("Story Bible sections")} tabs={tabs} />
      {tab === "characters" && recurring.length < editor.story_bible.characters.length && (
        <Button size="sm" variant="outline" onClick={() => setShowAllCharacters(!showAllCharacters)}>
          {showAllCharacters ? t("Show recurring characters only") : t("Show all source participants")}
        </Button>
      )}
      {tab === "removed" ? (
        <RemovedNames editor={editor} busy={restore.isPending} error={restore.error?.message}
          onRestore={(entry) => restore.mutate({ project, kind: EXCLUDED_KIND[entry.kind], name: entry.name, revision: editor.revision })} />
      ) : (
        <ul className="divide-y-[2px] divide-ink-black/10 border-y-[2px] border-ink-black/10">
          {entries(tab).map((entry) => (
            <EntityRow key={entry.id} editor={editor} kind={tab} entry={entry}
              onEdit={() => setSheet({ kind: tab, id: entry.id })}
              onMerge={() => setMerging({ kind: tab, entry })}
              onRemove={() => setRemoving({ kind: tab, entry })} />
          ))}
          {entries(tab).length === 0 && <li className="py-6 font-body text-sm text-ink-muted">{t("Nothing here yet.")}</li>}
        </ul>
      )}
      {open && (
        <EntitySheet key={`${open.kind}:${open.id ?? "new"}`} project={project} editor={editor} kind={open.kind} entityId={open.id}
          onClose={() => { setSheet(null); if (focus) onFocusClosed?.(); }} />
      )}
      {merging && <MergeSheet project={project} editor={editor} kind={merging.kind} entry={merging.entry} onClose={() => setMerging(null)} />}
      <ConfirmModal
        open={!!removing}
        destructive
        title={t("Remove {name}?", { name: removing?.entry.name ?? "" })}
        body={t("It leaves every scene and later extractions won't add it back. You can restore the name from Removed names.")}
        confirmLabel={t("Remove")}
        busy={remove.isPending}
        error={remove.error?.message}
        onClose={() => { setRemoving(null); remove.reset(); }}
        onConfirm={() => removing && remove.mutate(
          { project, kind: removing.kind, id: removing.entry.id, revision: editor.revision },
          { onSuccess: () => setRemoving(null) },
        )}
      />
    </section>
  );
}

function EntityRow({ editor, kind, entry, onEdit, onMerge, onRemove }: {
  editor: Editor; kind: EntityKind; entry: Entry;
  onEdit: () => void; onMerge: () => void; onRemove: () => void;
}) {
  const { t } = useI18n();
  const cited = editor.citations[entry.id] ?? [];
  const outdated = editor.references.some((ref) => ref.entity_id === entry.id && ref.status === "outdated");
  const lockedReason = cited.length ? t("Used in {parts}", { parts: cited.join(", ") }) : undefined;
  return (
    <li className="flex flex-wrap items-start gap-4 py-4">
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
          <span className="font-display text-lg font-bold">{entry.name}</span>
          {entry.origin === "author" && <span className="font-meta text-[0.6rem] uppercase tracking-[0.12em] text-narrator-gold">{t("Added by you")}</span>}
          {outdated && (
            <Link to={`../cast`} relative="path" className="font-meta text-[0.6rem] uppercase tracking-[0.12em] text-hero-red underline">
              {t("Cast image out of date")}
            </Link>
          )}
        </p>
        {!!entry.aliases?.length && <p className="font-body text-xs text-ink-muted">{t("Also: {names}", { names: entry.aliases.join(", ") })}</p>}
        <p className="mt-1 line-clamp-2 font-body text-sm text-ink-muted">{entry.visual_anchor}</p>
        {cited.length > 0 && <p className="mt-1 font-body text-xs text-ink-muted">{lockedReason}</p>}
      </div>
      <div className="flex flex-wrap gap-2">
        <Button size="xs" variant="outline" onClick={onEdit}>{t("Edit")}</Button>
        <Button size="xs" variant="outline" onClick={onMerge} disabled={cited.length > 0 || (editor.story_bible[kind] as unknown[]).length < 2}
          title={cited.length ? t("Restart those parts' adaptation to merge it away.") : undefined}>{t("Merge…")}</Button>
        <Button size="xs" variant="outline" onClick={onRemove} disabled={cited.length > 0}
          title={cited.length ? t("Restart those parts' adaptation to remove it.") : undefined}>{t("Remove")}</Button>
      </div>
    </li>
  );
}

function MergeSheet({ project, editor, kind, entry, onClose }: {
  project: string; editor: Editor; kind: EntityKind; entry: Entry; onClose: () => void;
}) {
  const { t } = useI18n();
  const merge = useMergeEntity();
  const others = (editor.story_bible[kind] as unknown as Entry[]).filter((item) => item.id !== entry.id);
  const [into, setInto] = useState(others[0]?.id ?? "");
  const target = others.find((item) => item.id === into);
  return (
    <Sheet open title={t("Merge {name}", { name: entry.name })} onClose={onClose}
      description={t("Use this when extraction found the same {kind} twice under different names.", { kind: t(KIND_LABELS[kind].one) })}
      footer={<>
        {merge.error && <p role="alert" className="mr-auto font-body text-sm text-hero-red">{merge.error.message}</p>}
        <Button variant="outline" onClick={onClose} disabled={merge.isPending}>{t("Cancel")}</Button>
        <Button disabled={!into || merge.isPending} onClick={() => merge.mutate(
          { project, kind, id: entry.id, into, revision: editor.revision }, { onSuccess: onClose },
        )}>{t("Merge")}</Button>
      </>}>
      <div className="space-y-4">
        <div>
          <FieldLabel htmlFor="merge-into">{t("Keep")}</FieldLabel>
          <SelectField id="merge-into" value={into} onChange={(event) => setInto(event.target.value)}>
            {others.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </SelectField>
        </div>
        {target && (
          <p className="font-body text-sm text-ink-muted">
            {t("{source} becomes another name for {target}. Its scenes and looks move to {target}, whose description and Cast image stay as they are.", { source: entry.name, target: target.name })}
          </p>
        )}
      </div>
    </Sheet>
  );
}

function RemovedNames({ editor, onRestore, busy, error }: {
  editor: Editor; onRestore: (entry: ExcludedEntity) => void; busy: boolean; error?: string;
}) {
  const { t } = useI18n();
  const excluded = editor.story_bible.excluded_entities ?? [];
  const kinds: Record<ExcludedEntity["kind"], string> = { character: t("Character"), location: t("Place"), prop: t("Prop") };
  return (
    <div className="space-y-3">
      <p className="font-body text-sm text-ink-muted">{t("Later extractions skip these names. Restore one to let extraction find it again.")}</p>
      {error && <p role="alert" className="font-body text-sm text-hero-red">{error}</p>}
      <ul className="divide-y-[2px] divide-ink-black/10 border-y-[2px] border-ink-black/10">
        {excluded.map((entry) => (
          <li key={`${entry.kind}:${entry.name}`} className="flex flex-wrap items-center gap-4 py-3">
            <span className="min-w-0 flex-1 font-body text-sm">
              <span className="font-bold">{entry.name}</span>
              <span className="ml-2 font-meta text-xs text-ink-muted">{kinds[entry.kind]}</span>
              {entry.aliases.length > 0 && <span className="ml-2 text-ink-muted">{t("Also: {names}", { names: entry.aliases.join(", ") })}</span>}
            </span>
            <Button size="xs" variant="outline" disabled={busy} onClick={() => onRestore(entry)}>{t("Restore")}</Button>
          </li>
        ))}
        {excluded.length === 0 && <li className="py-6 font-body text-sm text-ink-muted">{t("No removed names.")}</li>}
      </ul>
    </div>
  );
}

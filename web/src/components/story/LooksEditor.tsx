import { useState, type ReactNode } from "react";
import { useI18n } from "../../i18n";
import { Button } from "../ui/Button";
import { FieldLabel, SelectField, TextAreaField, TextField } from "../ui/Field";
import { anchorFromEdit, editableAnchor, readableAnchor } from "../../lib/visualAnchor";
import { useAddLook, useEditLook, useRemoveLook } from "../../api/seriesQueries";
import type { EntityKind, StoryBibleEditor } from "../../api/storyBible";
import type { AppearanceState } from "../../types/api";

interface LookDraft {
  label: string;
  visual_anchor: string;
  continuity_guard: string;
  visually_significant: boolean;
}

const EMPTY: LookDraft = { label: "", visual_anchor: "", continuity_guard: "", visually_significant: true };

function draftOf(look: AppearanceState): LookDraft {
  return {
    label: look.label, visual_anchor: editableAnchor(look.visual_anchor),
    continuity_guard: look.continuity_guard ?? "", visually_significant: look.visually_significant,
  };
}

/** Looks an entity takes on mid-story, each with its own complete description. */
export function LooksEditor({ project, editor, kind, entityId }: {
  project: string; editor: StoryBibleEditor; kind: EntityKind; entityId: string;
}) {
  const { t } = useI18n();
  const entity = (editor.story_bible[kind] as Array<{ id: string; appearance_states?: AppearanceState[] }>)
    .find((item) => item.id === entityId);
  const looks = entity?.appearance_states ?? [];
  const cited = editor.state_citations[entityId] ?? {};
  const [editing, setEditing] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<LookDraft>(EMPTY);
  const [startsAt, setStartsAt] = useState("");
  const [error, setError] = useState<string | null>(null);
  const add = useAddLook();
  const edit = useEditLook();
  const remove = useRemoveLook();
  const busy = add.isPending || edit.isPending || remove.isPending;
  const onError = (err: Error) => setError(err.message);

  function details(value: LookDraft, original?: AppearanceState) {
    return {
      label: value.label.trim(), visual_anchor: anchorFromEdit(value.visual_anchor, original?.visual_anchor),
      continuity_guard: original && value.continuity_guard === (original.continuity_guard ?? "")
        ? original.continuity_guard : value.continuity_guard.trim() || null,
      visually_significant: value.visually_significant,
    };
  }

  return (
    <section className="space-y-3 border-t-[2px] border-ink-black/10 pt-5" aria-label={t("Looks")}>
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h3 className="font-display text-xl font-black uppercase">{t("Looks")}</h3>
        {!adding && <Button size="xs" variant="outline" onClick={() => { setAdding(true); setDraft(EMPTY); setEditing(null); }}>{t("Add a look")}</Button>}
      </div>
      <p className="font-body text-xs text-ink-muted">{t("A look is a lasting change in appearance, such as a new outfit or an injury. Describe the whole look, not only what changed.")}</p>
      {error && <p role="alert" className="font-body text-sm text-hero-red">{error}</p>}
      <ul className="space-y-3">
        {looks.map((look) => {
          const usedBy = cited[look.id] ?? [];
          return (
            <li key={look.id} className="bg-surface-container p-4">
              {editing === look.id ? (
                <LookForm value={draft} onChange={setDraft} busy={busy}
                  onCancel={() => setEditing(null)}
                  onSubmit={() => edit.mutate({ project, kind, id: entityId, stateId: look.id, revision: editor.revision, changes: details(draft, look) },
                    { onSuccess: () => setEditing(null), onError })} />
              ) : (
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <p className="font-display text-base font-bold">{look.label}</p>
                    <p className="mt-1 font-body text-sm text-ink-muted">{readableAnchor(look.visual_anchor)}</p>
                    {usedBy.length > 0 && <p className="mt-1 font-body text-xs text-ink-muted">{t("Used in {parts}", { parts: usedBy.join(", ") })}</p>}
                  </div>
                  <div className="flex gap-2">
                    <Button size="xs" variant="outline" disabled={busy} onClick={() => { setEditing(look.id); setDraft(draftOf(look)); setAdding(false); }}>{t("Edit")}</Button>
                    <Button size="xs" variant="outline" disabled={busy || usedBy.length > 0}
                      title={usedBy.length ? t("Used in {parts}", { parts: usedBy.join(", ") }) : undefined}
                      onClick={() => remove.mutate({ project, kind, id: entityId, stateId: look.id, revision: editor.revision }, { onError })}>
                      {t("Remove")}
                    </Button>
                  </div>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {adding && (
        <div className="bg-surface-container p-4">
          <LookForm value={draft} onChange={setDraft} busy={busy} onCancel={() => setAdding(false)}
            extra={<div>
              <FieldLabel htmlFor="look-starts-at">{t("Begins at")}</FieldLabel>
              <SelectField id="look-starts-at" value={startsAt} onChange={(event) => setStartsAt(event.target.value)}>
                <option value="">{t("Not tied to a scene")}</option>
                {editor.story_bible.scenes.map((scene, index) => (
                  <option key={scene.id} value={scene.id}>{`${String(index + 1).padStart(2, "0")} · ${scene.title}`}</option>
                ))}
              </SelectField>
            </div>}
            onSubmit={() => add.mutate({ project, kind, id: entityId, revision: editor.revision, details: details(draft), startsAtScene: startsAt || null },
              { onSuccess: () => { setAdding(false); setStartsAt(""); }, onError })} />
        </div>
      )}
    </section>
  );
}

function LookForm({ value, onChange, onSubmit, onCancel, busy, extra }: {
  value: LookDraft; onChange: (value: LookDraft) => void; onSubmit: () => void; onCancel: () => void;
  busy: boolean; extra?: ReactNode;
}) {
  const { t } = useI18n();
  const ready = value.label.trim() && value.visual_anchor.trim();
  return (
    <div className="space-y-4">
      <div>
        <FieldLabel htmlFor="look-label">{t("Label")} *</FieldLabel>
        <TextField id="look-label" value={value.label} maxLength={120} placeholder={t("e.g. Storm gear")}
          onChange={(event) => onChange({ ...value, label: event.target.value })} />
      </div>
      <div>
        <FieldLabel htmlFor="look-anchor">{t("Complete description of this look")} *</FieldLabel>
        <TextAreaField id="look-anchor" rows={3} value={value.visual_anchor}
          onChange={(event) => onChange({ ...value, visual_anchor: event.target.value })} />
      </div>
      <div>
        <FieldLabel htmlFor="look-guard">{t("Continuity note (optional)")}</FieldLabel>
        <TextField id="look-guard" value={value.continuity_guard} placeholder={t("e.g. the left arm stays in a sling")}
          onChange={(event) => onChange({ ...value, continuity_guard: event.target.value })} />
      </div>
      <label className="flex min-h-11 items-center gap-3 font-body text-sm">
        <input type="checkbox" className="h-5 w-5" checked={value.visually_significant}
          onChange={(event) => onChange({ ...value, visually_significant: event.target.checked })} />
        {t("Needs its own Cast image")}
      </label>
      {extra}
      <div className="flex flex-wrap justify-end gap-2">
        <Button size="sm" variant="outline" onClick={onCancel} disabled={busy}>{t("Cancel")}</Button>
        <Button size="sm" onClick={onSubmit} disabled={busy || !ready}>{t("Save look")}</Button>
      </div>
    </div>
  );
}

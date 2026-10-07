import { ErrorNotice } from "../composites/ErrorNotice";
import { useState, type ReactNode } from "react";
import { useI18n } from "../../i18n";
import { Sheet } from "../composites/Sheet";
import { Button } from "../ui/Button";
import { CreditAmount } from "../ui/CreditAmount";
import { FieldLabel, SelectField, TextAreaField, TextField } from "../ui/Field";
import { LooksEditor } from "./LooksEditor";
import { KIND_LABELS } from "./entityKinds";
import { anchorFromEdit, editableAnchor } from "../../lib/visualAnchor";
import { useAddEntity, useDraftEntity, useDraftEstimate, useEditEntity } from "../../api/seriesQueries";
import type { EntityKind, StoryBibleEditor } from "../../api/storyBible";
import type { CharacterRelationship, ReferenceForm } from "../../types/api";

type FieldShape = "text" | "textarea" | "lines" | "aliases";
interface FieldSpec { key: string; label: string; shape: FieldShape; required?: boolean; help?: string }

const FIELDS: Record<EntityKind, FieldSpec[]> = {
  characters: [
    { key: "name", label: "Name", shape: "text", required: true },
    { key: "aliases", label: "Other names", shape: "aliases", help: "Separate names with commas. Extraction recognizes these too." },
    { key: "visual_anchor", label: "Physical description", shape: "textarea", required: true, help: "Comma-separated physical tags: build, face, hair, usual clothing. No emotion, pose or action." },
    { key: "age_range", label: "Age", shape: "text" },
    { key: "gender", label: "Gender", shape: "text" },
    { key: "stature", label: "Unusual stature", shape: "text", help: "Only for an unusual body scale: height plus a comparison, e.g. 'two and a half feet tall; head reaches an adult's waist'." },
    { key: "distinguishing_features", label: "Distinguishing features", shape: "lines", help: "One per line: permanent details true for the whole story." },
    { key: "default_outfit", label: "Usual outfit", shape: "text" },
    { key: "baseline_affect", label: "Usual demeanor", shape: "text" },
  ],
  locations: [
    { key: "name", label: "Name", shape: "text", required: true },
    { key: "aliases", label: "Other names", shape: "aliases", help: "Separate names with commas. Extraction recognizes these too." },
    { key: "visual_anchor", label: "Physical description", shape: "textarea", required: true, help: "Comma-separated environment tags of how the place looks when it first appears." },
    { key: "time_of_day", label: "Time of day", shape: "text" },
    { key: "mood", label: "Mood", shape: "text" },
  ],
  props: [
    { key: "name", label: "Name", shape: "text", required: true },
    { key: "aliases", label: "Other names", shape: "aliases", help: "Separate names with commas. Extraction recognizes these too." },
    { key: "visual_anchor", label: "Physical description", shape: "textarea", required: true, help: "What the object looks like: material, size, color, shape and condition." },
  ],
};

const NULLABLE = new Set(["baseline_affect", "time_of_day"]);

const REFERENCE_FORMS: Array<{ value: ReferenceForm; label: string }> = [
  { value: "figure", label: "Turnaround: people and animals" },
  { value: "form", label: "Form study: no fixed front, back or head" },
  { value: "formation", label: "Formation: a group sharing one design" },
];

function toForm(spec: FieldSpec, value: unknown): string {
  if (Array.isArray(value)) return value.join(spec.shape === "aliases" ? ", " : "\n");
  if (spec.key === "visual_anchor") return editableAnchor(value == null ? "" : String(value));
  return value == null ? "" : String(value);
}

function toPayload(spec: FieldSpec, value: string): unknown {
  if (spec.shape === "aliases") return value.split(",").map((item) => item.trim()).filter(Boolean);
  if (spec.shape === "lines") return value.split("\n").map((item) => item.trim()).filter(Boolean);
  const text = value.trim();
  return NULLABLE.has(spec.key) && !text ? null : text;
}

interface Props {
  project: string;
  editor: StoryBibleEditor;
  kind: EntityKind;
  /** The entity to edit; omitted when adding. */
  entityId?: string;
  onClose: () => void;
  /** Rarer, weightier actions shown after the details, e.g. merge and remove. */
  actions?: ReactNode;
}

export function EntitySheet({ project, editor, kind, entityId, onClose, actions }: Props) {
  const { t } = useI18n();
  const entities = editor.story_bible[kind] as unknown as Array<Record<string, unknown> & { id: string; name: string }>;
  const entity = entityId ? entities.find((item) => item.id === entityId) : undefined;
  const specs = FIELDS[kind];
  const [values, setValues] = useState<Record<string, string>>(() =>
    Object.fromEntries(specs.map((spec) => [spec.key, toForm(spec, entity?.[spec.key])])));
  const [originalAnchor, setOriginalAnchor] = useState(String(entity?.visual_anchor ?? ""));
  const [relationships, setRelationships] = useState<CharacterRelationship[]>(
    () => (entity?.relationships as CharacterRelationship[] | undefined) ?? []);
  const [scenes, setScenes] = useState<string[]>([]);
  const [castRequired, setCastRequired] = useState(entity?.cast_required === true);
  const savedForm = (entity?.reference_form as ReferenceForm | undefined) ?? "figure";
  const [referenceForm, setReferenceForm] = useState<ReferenceForm>(savedForm);
  const [error, setError] = useState<Error | string | null>(null);
  const edit = useEditEntity();
  const add = useAddEntity();
  const busy = edit.isPending || add.isPending;
  const adding = !entityId;
  if (!adding && !entity) {
    return <Sheet open title={t("Not in the Story Bible")} onClose={onClose}><p className="font-body text-sm">{t("This entry was removed or merged. Close to see the current Story Bible.")}</p></Sheet>;
  }
  const missing = specs.filter((spec) => spec.required && !values[spec.key]?.trim()).map((spec) => t(spec.label));
  const needsScene = adding && kind === "characters" && scenes.length === 0;

  function payload(): Record<string, unknown> {
    const result: Record<string, unknown> = {};
    for (const spec of specs) {
      const next = spec.key === "visual_anchor"
        ? anchorFromEdit(values[spec.key] ?? "", originalAnchor)
        : toPayload(spec, values[spec.key] ?? "");
      if (adding ? (next !== "" && next !== null && !(Array.isArray(next) && !next.length))
        : JSON.stringify(next) !== JSON.stringify(entity?.[spec.key] ?? (NULLABLE.has(spec.key) ? null : spec.shape === "text" || spec.shape === "textarea" ? "" : []))) {
        result[spec.key] = next;
      }
    }
    if (kind === "characters" && !adding) {
      if (castRequired !== (entity?.cast_required === true)) result.cast_required = castRequired;
      if (referenceForm !== savedForm) result.reference_form = referenceForm;
      const cleaned = relationships.filter((rel) => rel.character_id && rel.relationship.trim())
        .map((rel) => ({ character_id: rel.character_id, relationship: rel.relationship.trim() }));
      if (JSON.stringify(cleaned) !== JSON.stringify(entity?.relationships ?? [])) result.relationships = cleaned;
    }
    return result;
  }

  function save() {
    setError(null);
    const details = payload();
    const onError = (err: Error) => setError(err);
    if (adding) {
      add.mutate({ project, kind, revision: editor.revision, details, sceneIds: scenes }, { onSuccess: onClose, onError });
    } else if (Object.keys(details).length) {
      edit.mutate({ project, kind, id: entityId!, revision: editor.revision, changes: details }, { onSuccess: onClose, onError });
    } else {
      onClose();
    }
  }

  const title = adding ? t(KIND_LABELS[kind].add) : t("Edit {name}", { name: entity!.name });
  return (
    <Sheet
      open
      wide
      title={title}
      onClose={onClose}
      description={adding
        ? t("Add someone or something extraction missed. New entries need Cast references before a part can use them.")
        : t("Changing a description marks this entry's Cast images out of date; you choose to regenerate or keep them. Drawn pages are flagged, never redrawn.")}
      footer={<>
        {error && <ErrorNotice error={error} operation="save" />}
        <Button variant="outline" onClick={onClose} disabled={busy}>{t("Cancel")}</Button>
        <Button onClick={save} disabled={busy || missing.length > 0 || needsScene}>
          {busy ? t("Saving…") : adding ? t("Add to the Story Bible") : t("Save changes")}
        </Button>
      </>}
    >
      <div className="space-y-6">
        {adding && <DraftFromSource project={project} kind={kind} name={values.name ?? ""}
          aliases={toPayload(specs[1], values.aliases ?? "") as string[]}
          onDraft={(details, suggested) => {
            if (!values.visual_anchor?.trim()) setOriginalAnchor(String(details.visual_anchor ?? ""));
            setValues((current) => Object.fromEntries(specs.map((spec) => [
              spec.key, current[spec.key]?.trim() ? current[spec.key] : toForm(spec, details[spec.key]),
            ])));
            if (suggested.length && !scenes.length) setScenes(kind === "props" ? suggested.slice(0, 1) : suggested);
          }} />}
        <div className="grid gap-5 md:grid-cols-2">
          {specs.map((spec) => (
            <div key={spec.key} className={spec.shape === "textarea" || spec.shape === "lines" ? "md:col-span-2" : undefined}>
              <FieldLabel htmlFor={`entity-${spec.key}`}>{t(spec.label)}{spec.required ? " *" : ""}</FieldLabel>
              {spec.shape === "textarea" || spec.shape === "lines" ? (
                <TextAreaField id={`entity-${spec.key}`} rows={spec.shape === "lines" ? 3 : 4} value={values[spec.key] ?? ""}
                  onChange={(event) => setValues({ ...values, [spec.key]: event.target.value })} />
              ) : (
                <TextField id={`entity-${spec.key}`} value={values[spec.key] ?? ""} maxLength={spec.key === "name" ? 200 : undefined}
                  onChange={(event) => setValues({ ...values, [spec.key]: event.target.value })} />
              )}
              {spec.help && <p className="mt-1.5 font-body text-xs text-ink-muted">{t(spec.help)}</p>}
            </div>
          ))}
        </div>
        {kind === "characters" && !adding && (
          <label className="flex min-h-11 items-start gap-3 font-body text-sm">
            <input type="checkbox" className="mt-0.5 h-5 w-5 shrink-0" checked={castRequired} disabled={busy}
              onChange={(event) => setCastRequired(event.target.checked)} />
            <span>{t("Include in Cast even for a brief appearance")}
              <span className="mt-1 block text-xs text-ink-muted">{t("Recurring and author-added characters are already included.")}</span>
            </span>
          </label>
        )}
        {kind === "characters" && !adding && (
          <div>
            <FieldLabel htmlFor="entity-reference_form">{t("Reference sheet")}</FieldLabel>
            <SelectField id="entity-reference_form" value={referenceForm} disabled={busy} className="max-w-md"
              onChange={(event) => setReferenceForm(event.target.value as ReferenceForm)}>
              {REFERENCE_FORMS.map((option) => (
                <option key={option.value} value={option.value}
                  disabled={option.value === "formation" && entity?.identity_kind !== "group"}>
                  {t(option.label)}
                </option>
              ))}
            </SelectField>
            <p className="mt-1.5 font-body text-xs text-ink-muted">
              {t("How Cast lays out this character's reference. A turnaround fits anyone with a face and a fixed body; a form study suits a floating eye or a living cloud; a formation shows a group whose members share one design. Changing it marks the reference out of date.")}
            </p>
          </div>
        )}
        {kind === "characters" && !adding && (
          <Relationships editor={editor} self={entityId!} value={relationships} onChange={setRelationships} />
        )}
        {adding && <ScenePicker editor={editor} kind={kind} value={scenes} onChange={setScenes} />}
        {!adding && <LooksEditor project={project} editor={editor} kind={kind} entityId={entityId!} />}
        {missing.length > 0 && <p className="font-body text-xs text-ink-muted">{t("Required: {fields}", { fields: missing.join(", ") })}</p>}
        {actions}
      </div>
    </Sheet>
  );
}

function DraftFromSource({ project, kind, name, aliases, onDraft }: {
  project: string; kind: EntityKind; name: string; aliases: string[];
  onDraft: (details: Record<string, unknown>, suggestedScenes: string[]) => void;
}) {
  const { t } = useI18n();
  const estimate = useDraftEstimate(project, kind, name, aliases);
  const draft = useDraftEntity();
  const ready = name.trim().length >= 2;
  return (
    <div className="flex flex-wrap items-center gap-3 bg-surface-container p-4">
      <div className="min-w-0 flex-1 font-body text-sm text-ink-muted">
        {!ready ? t("Type a name to draft the details from the passages that mention it.")
          : estimate.data && !estimate.data.mentioned ? (estimate.data.message ?? t("The source never mentions that name."))
          : t("Drafts the details from the passages that mention this name. Nothing is saved until you add it.")}
      </div>
      <Button size="sm" variant="secondary"
        disabled={!ready || !estimate.data?.mentioned || draft.isPending}
        onClick={() => draft.mutate({ project, kind, name: name.trim(), aliases }, {
          onSuccess: (result) => onDraft(result.details, result.suggested_scene_ids),
        })}>
        {draft.isPending ? t("Drafting…") : t("Draft from source")}
        {estimate.data?.estimate && <CreditAmount value={estimate.data.estimate.estimate_credits} approximate />}
      </Button>
      {draft.error && <ErrorNotice error={draft.error} operation="generate" />}
    </div>
  );
}

function Relationships({ editor, self, value, onChange }: {
  editor: StoryBibleEditor; self: string; value: CharacterRelationship[]; onChange: (value: CharacterRelationship[]) => void;
}) {
  const { t } = useI18n();
  const others = editor.story_bible.characters.filter((character) => character.id !== self);
  return (
    <fieldset className="space-y-3">
      <legend className="ui-field-label">{t("Relationships")}</legend>
      {value.map((rel, index) => (
        <div key={index} className="flex flex-wrap items-center gap-2">
          <SelectField aria-label={t("Related character")} value={rel.character_id} className="max-w-[16rem]"
            onChange={(event) => onChange(value.map((item, i) => i === index ? { ...item, character_id: event.target.value } : item))}>
            <option value="">{t("Choose a character")}</option>
            {others.map((character) => <option key={character.id} value={character.id}>{character.name}</option>)}
          </SelectField>
          <TextField aria-label={t("Relationship")} placeholder={t("e.g. sister")} value={rel.relationship} className="max-w-[16rem]"
            onChange={(event) => onChange(value.map((item, i) => i === index ? { ...item, relationship: event.target.value } : item))} />
          <Button size="xs" variant="outline" onClick={() => onChange(value.filter((_, i) => i !== index))}>{t("Remove")}</Button>
        </div>
      ))}
      {others.length > 0 && (
        <Button size="xs" variant="outline" onClick={() => onChange([...value, { character_id: "", relationship: "" }])}>{t("Add a relationship")}</Button>
      )}
    </fieldset>
  );
}

function ScenePicker({ editor, kind, value, onChange }: {
  editor: StoryBibleEditor; kind: EntityKind; value: string[]; onChange: (value: string[]) => void;
}) {
  const { t } = useI18n();
  const editable = new Set(editor.editable_scene_ids);
  const titles = new Map(editor.parts.map((part) => [part.id, part.title]));
  const places = new Map(editor.story_bible.locations.map((location) => [location.id, location.name]));
  const scenes = editor.story_bible.scenes;
  const single = kind === "props";
  const legend = kind === "characters" ? t("Scenes this character appears in *")
    : kind === "locations" ? t("Scenes that take place here") : t("Scene where it first appears");
  return (
    <fieldset className="space-y-3">
      <legend className="ui-field-label">{legend}</legend>
      <p className="font-body text-xs text-ink-muted">
        {kind === "locations"
          ? t("Chosen scenes move here from the place they were set. Scenes in parts that are already adapted can't change.")
          : t("Scenes in parts that are already adapted can't change.")}
      </p>
      {editable.size === 0 && <p className="font-body text-sm">{t("Every part is adapted, so new entries can't join its scenes. Add the next part first.")}</p>}
      <ul className="max-h-72 space-y-1 overflow-y-auto">
        {scenes.map((scene, index) => {
          const enabled = editable.has(scene.id);
          const checked = value.includes(scene.id);
          return (
            <li key={scene.id}>
              <label className="flex min-h-11 items-center gap-3 font-body text-sm aria-disabled:opacity-50" aria-disabled={!enabled}>
                <input type={single ? "radio" : "checkbox"} name="entity-scenes" className="h-5 w-5" disabled={!enabled} checked={checked}
                  onChange={(event) => onChange(single ? [scene.id] : event.target.checked ? [...value, scene.id] : value.filter((id) => id !== scene.id))} />
                <span className="font-meta text-xs tabular-nums text-ink-muted">{String(index + 1).padStart(2, "0")}</span>
                <span className="min-w-0 truncate">{scene.title}</span>
                <span className="ml-auto shrink-0 font-meta text-[0.65rem] text-ink-muted">
                  {[scene.part_id ? titles.get(scene.part_id) : null, kind === "locations" && scene.location_id !== null ? places.get(scene.location_id) : null].filter(Boolean).join(" · ")}
                </span>
              </label>
            </li>
          );
        })}
      </ul>
    </fieldset>
  );
}

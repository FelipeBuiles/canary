import { apiFetch } from "./client";
import { seriesPath } from "./projectScope";
import type { CostEstimate, StoryBible } from "../types/api";

export type EntityKind = "characters" | "locations" | "props";

/** A Cast reference after edits: current, out of date (its entity changed) or missing. */
export interface ReferenceFreshness {
  kind: EntityKind;
  entity_id: string;
  state_id: string | null;
  status: "current" | "outdated" | "missing";
}

/** One author edit, described by names so the editor can say what Undo reverses. */
export interface StoryBibleChange {
  action: "edit" | "add" | "remove" | "merge" | "add_look" | "edit_look" | "remove_look" | "restore";
  kind: EntityKind;
  entity_id?: string;
  name: string;
  into?: string;
  look?: string;
}

/** Two entries that may be one found twice; a suggestion to compare, never applied. */
export interface PossibleDuplicate {
  kind: EntityKind;
  ids: [string, string];
  reason: "same_name" | "name_within";
}

/** What removing or merging an entry would change. Previews never write. */
export interface EditImpact {
  action: "remove" | "merge";
  /** Why the edit can't happen, e.g. an adapted part uses the entry. */
  blocked: string | null;
  /** Scenes the entry leaves (remove) or that move to the kept entry (merge). */
  scenes: { id: string; title: string; part_id: string | null }[];
  looks: string[];
  relationships: number;
  /** Names that become other names for the kept entry (merge). */
  aliases: string[];
  /** Existing Cast images of the entry that stop being used. */
  cast_images: number;
  /** References Cast would need afterwards that don't exist yet. */
  new_references: number;
  reopens_cast: boolean;
}

export interface StoryBibleEditor {
  story_bible: StoryBible;
  /** The newest author edit, while nothing has changed the Bible since; blocked says why it can't be undone. */
  undo: { change: StoryBibleChange; blocked: string | null } | null;
  possible_duplicates: PossibleDuplicate[];
  revision: number;
  parts: { id: string; title: string; ordinal: number }[];
  /** Scenes in parts whose adaptation hasn't started: new entities can join them. */
  editable_scene_ids: string[];
  /** Adapted parts (by title) that name each entity; those can't be removed or merged away. */
  citations: Record<string, string[]>;
  state_citations: Record<string, Record<string, string[]>>;
  references: ReferenceFreshness[];
}

export interface SavedStoryBible {
  story_bible: StoryBible;
  revision: number;
  entity_id?: string;
  state_id?: string;
}

export interface EntityDraft {
  details: Record<string, unknown>;
  /** Editable scenes that mention the name. */
  suggested_scene_ids: string[];
  mentioned_scene_ids: string[];
}

const base = (project: string) => `${seriesPath(project)}/story-bible`;
const entity = (project: string, kind: EntityKind, id: string) =>
  `${base(project)}/${kind}/${encodeURIComponent(id)}`;

export function getStoryBibleEditor(project: string): Promise<StoryBibleEditor> {
  return apiFetch(`${base(project)}/editor`);
}

export function editEntity(
  project: string, kind: EntityKind, id: string, expectedRevision: number, changes: Record<string, unknown>,
): Promise<SavedStoryBible> {
  return apiFetch(entity(project, kind, id), {
    method: "PATCH",
    body: JSON.stringify({ expected_revision: expectedRevision, changes }),
  });
}

export function addEntity(
  project: string, kind: EntityKind, expectedRevision: number, details: Record<string, unknown>, sceneIds: string[],
): Promise<SavedStoryBible> {
  return apiFetch(`${base(project)}/${kind}`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision, details, scene_ids: sceneIds }),
  });
}

export function removeEntity(project: string, kind: EntityKind, id: string, expectedRevision: number): Promise<SavedStoryBible> {
  return apiFetch(`${entity(project, kind, id)}?expected_revision=${expectedRevision}`, { method: "DELETE" });
}

export function mergeEntity(
  project: string, kind: EntityKind, id: string, into: string, expectedRevision: number,
): Promise<SavedStoryBible> {
  return apiFetch(`${entity(project, kind, id)}/merge`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision, into }),
  });
}

export function getEditImpact(
  project: string, kind: EntityKind, id: string, action: "remove" | "merge", into?: string,
): Promise<EditImpact> {
  const params = new URLSearchParams({ action });
  if (into) params.set("into", into);
  return apiFetch(`${entity(project, kind, id)}/impact?${params}`);
}

export function undoLastEdit(project: string, expectedRevision: number): Promise<SavedStoryBible & { undone: StoryBibleChange }> {
  return apiFetch(`${base(project)}/undo`, { method: "POST", body: JSON.stringify({ expected_revision: expectedRevision }) });
}

export function addLook(
  project: string, kind: EntityKind, id: string, expectedRevision: number,
  details: Record<string, unknown>, startsAtScene: string | null,
): Promise<SavedStoryBible> {
  return apiFetch(`${entity(project, kind, id)}/states`, {
    method: "POST",
    body: JSON.stringify({ expected_revision: expectedRevision, details, starts_at_scene: startsAtScene }),
  });
}

export function editLook(
  project: string, kind: EntityKind, id: string, stateId: string, expectedRevision: number,
  changes: Record<string, unknown>,
): Promise<SavedStoryBible> {
  return apiFetch(`${entity(project, kind, id)}/states/${encodeURIComponent(stateId)}`, {
    method: "PATCH",
    body: JSON.stringify({ expected_revision: expectedRevision, changes }),
  });
}

export function removeLook(
  project: string, kind: EntityKind, id: string, stateId: string, expectedRevision: number,
): Promise<SavedStoryBible> {
  return apiFetch(
    `${entity(project, kind, id)}/states/${encodeURIComponent(stateId)}?expected_revision=${expectedRevision}`,
    { method: "DELETE" },
  );
}

export function restoreExcluded(
  project: string, kind: EntityKind, name: string, expectedRevision: number,
): Promise<SavedStoryBible> {
  return apiFetch(
    `${base(project)}/excluded/${kind}/${encodeURIComponent(name)}?expected_revision=${expectedRevision}`,
    { method: "DELETE" },
  );
}

/** Fill a blank visual anchor in place; an existing anchor is never overwritten. */
export function fillVisualAnchor(
  project: string,
  body: { entity_id: string; appearance_state_id: string | null; visual_anchor: string },
): Promise<SavedStoryBible & { missing_visual_anchors: string[] }> {
  return apiFetch(`${base(project)}/visual-anchor`, { method: "POST", body: JSON.stringify(body) });
}

export interface DraftEstimate {
  /** Whether any part's source mentions the name. */
  mentioned: boolean;
  message?: string;
  estimate?: CostEstimate;
  mentioned_scene_ids: string[];
}

export function getDraftEstimate(
  project: string, kind: EntityKind, name: string, aliases: string[] = [],
): Promise<DraftEstimate> {
  const params = new URLSearchParams({ name });
  for (const alias of aliases) params.append("aliases", alias);
  return apiFetch(`${base(project)}/${kind}/draft-estimate?${params}`);
}

export function draftEntity(
  project: string, kind: EntityKind, request: { name: string; aliases?: string[]; note?: string },
): Promise<EntityDraft> {
  return apiFetch(`${base(project)}/${kind}/draft`, { paidAction: true, method: "POST", body: JSON.stringify(request) });
}

export function getCastFreshness(project: string): Promise<{ references: ReferenceFreshness[] }> {
  return apiFetch(`${seriesPath(project)}/cast/freshness`);
}

export function keepReference(
  project: string, kind: EntityKind, entityId: string, stateId: string | null,
): Promise<{ references: ReferenceFreshness[] }> {
  return apiFetch(`${seriesPath(project)}/cast/references/keep`, {
    method: "POST",
    body: JSON.stringify({ kind, entity_id: entityId, state_id: stateId }),
  });
}

export function reopenCast(project: string): Promise<{ reopened: boolean; references: ReferenceFreshness[] }> {
  return apiFetch(`${seriesPath(project)}/cast/reopen`, { method: "POST" });
}

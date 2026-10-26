import { createContext, useContext, useEffect, useState } from "react";
import { seriesPath } from "../../api/projectScope";
import type { EntityKind } from "../../api/storyBible";
import type { AppearanceState, CastFailure, Character, Location, Prop } from "../../types/api";
import { versionedUrl } from "../../lib/assetVersions";

export type CastKind = "character" | "location" | "prop";
export type CastEntry =
  | { kind: "character"; entity: Character }
  | { kind: "location"; entity: Location }
  | { kind: "prop"; entity: Prop };

export const STORY_KIND: Record<CastKind, EntityKind> = { character: "characters", location: "locations", prop: "props" };

/** Sheets are wide model sheets, plates are scenes, prop refs are square. */
export const ASPECT: Record<CastKind, number> = { character: 3 / 2, location: 16 / 9, prop: 1 };

const filesBase = (project: string) => `/api${seriesPath(project)}/files`;

/** The main reference image, relative to the series files root (`raw` keeps the id unencoded). */
export function mainImagePath(kind: CastKind, id: string, raw = false) {
  const entity = raw ? id : encodeURIComponent(id);
  if (kind === "character") return `refs/${entity}/sheet.png`;
  if (kind === "location") return `plates/${entity}.png`;
  return `refs/props/${entity}/ref.png`;
}

export const mainImageUrl = (project: string, kind: CastKind, id: string) => `${filesBase(project)}/${mainImagePath(kind, id)}`;

/** A look's full image: a character's look sheet, or a place's state plate. */
export function lookImageUrl(project: string, kind: CastKind, id: string, stateId: string) {
  const entity = encodeURIComponent(id);
  const state = encodeURIComponent(stateId);
  return kind === "character"
    ? `${filesBase(project)}/refs/${entity}/states/${state}/sheet.png`
    : `${filesBase(project)}/plates/${entity}/states/${state}.png`;
}

/** A look's small image: a character's look portrait, or the place's state plate. */
export function lookThumbUrl(project: string, kind: CastKind, id: string, stateId: string) {
  return kind === "character"
    ? `${filesBase(project)}/refs/${encodeURIComponent(id)}/states/${encodeURIComponent(stateId)}/portrait.png`
    : lookImageUrl(project, kind, id, stateId);
}

/** The face crop pages use for close shots; the roster shows it as the character's thumbnail. */
export const portraitUrl = (project: string, id: string) => `${filesBase(project)}/refs/${encodeURIComponent(id)}/portrait.png`;

/**
 * The small WebP of a project image URL, for tiles that show it at a few dozen
 * pixels (`card` for sheet-grid cards). The query token carries over, so the
 * rendition renews exactly when the master does, and shares its version.
 */
export function thumbnailUrl(src: string, rendition: "thumbnail" | "card" = "thumbnail") {
  return versionedUrl(src.replace("/files/", `/thumbnails/${rendition}/`));
}

export function looksOf(entry: CastEntry): AppearanceState[] {
  if (entry.kind === "prop") return [];
  return (entry.entity.appearance_states ?? []).filter((state) => state.visually_significant);
}

export function castFailureFor(failures: CastFailure[] | undefined, entityId: string, stateId: string | null) {
  return failures?.find((failure) => failure.entity_id === entityId && failure.state_id === stateId);
}

/** The roster and sheet address an entry the way failure and review links do. */
export const entryAnchor = (kind: CastKind, id: string) => `cast-${kind}-${id}`;

/**
 * References the running Cast stage has yet to redraw. An existing image is
 * not proof of a finished reference: while Cast updates changed entries,
 * their old images stay on disk until each new one lands.
 */
export const CastUpdatingContext = createContext<ReadonlySet<string>>(new Set());
export const updatingKey = (kind: EntityKind, entityId: string, stateId: string | null = null) => `${kind}:${entityId}:${stateId ?? ""}`;

export type CastSuggestion = { kind: CastKind; entityId: string; stateId?: string | null; text: string; nonce: number };
export const CastSuggestionContext = createContext<{ suggestion?: CastSuggestion; clear: () => void }>({ clear: () => undefined });

/**
 * Applies one reference's suggested direction, once per suggestion. The room
 * selects the reference; applying never spends — the author still reviews
 * the direction and its cost. `states` takes suggestions for its looks.
 */
export function useCastSuggestion(kind: CastKind, entityId: string, apply: (text: string, stateId: string | null) => void, states = false) {
  const { suggestion, clear } = useContext(CastSuggestionContext);
  const [applied, setApplied] = useState<number | null>(null);
  const match = suggestion && suggestion.kind === kind && suggestion.entityId === entityId && !!suggestion.stateId === states
    ? suggestion : undefined;
  // Applied while rendering so the direction is in place on the first paint.
  if (match && match.nonce !== applied) {
    setApplied(match.nonce);
    apply(match.text.trim().slice(0, 500), match.stateId ?? null);
  }
  useEffect(() => {
    if (match && match.nonce === applied) clear();
  }, [match, applied, clear]);
}

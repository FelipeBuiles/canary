/**
 * Visual anchors are prompt text. Extract writes characters and places as
 * comma-separated image-model tags ("1woman, adult female, grey hair") that
 * reach every image request verbatim, so the anchor itself never changes.
 * This only decides how an anchor reads on screen.
 */

/** A bare subject-count tag: "1man", "1woman", "1cat", "2girls". Not "3d", "30s", "1920s". */
const COUNT_TAG = /^[1-9][a-z]{3,}$/i;
/** A count glued to a longer tag: "1male rat-like humanoid" → "male rat-like humanoid". */
const COUNT_PREFIX = /^[1-9](?=[a-z]{3,}\s)/i;
/** Prose anchors (props, transient objects) already read as sentences. */
const SENTENCE = /[.!?](\s|$)/;

export function readableAnchor(anchor: string | null | undefined): string {
  const text = (anchor ?? "").trim();
  if (!text || SENTENCE.test(text)) return text;
  const seen = new Set<string>();
  const tags = text.split(",")
    .map((tag) => tag.trim().replace(COUNT_PREFIX, ""))
    .filter((tag) => {
      const key = tag.toLocaleLowerCase();
      if (!tag || COUNT_TAG.test(tag) || seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  if (tags.length === 0) return "";
  const sentence = tags.join(", ");
  return `${sentence.charAt(0).toLocaleUpperCase()}${sentence.slice(1)}.`;
}

export interface MissingVisualAnchor {
  key: string;
  entityId: string;
  stateId: string | null;
  name: string;
}

interface AnchoredEntity {
  id: string;
  name: string;
  visual_anchor: string;
  appearance_states?: { id: string; label: string; visual_anchor: string }[];
}

/** Entries Plan cannot use: a blank base or appearance-state anchor (mirrors the server check). */
export function missingVisualAnchors(entities: AnchoredEntity[]): MissingVisualAnchor[] {
  return entities.flatMap((entity) => [
    ...(entity.visual_anchor.trim() ? [] : [{ key: entity.id, entityId: entity.id, stateId: null, name: entity.name }]),
    ...(entity.appearance_states ?? [])
      .filter((state) => !state.visual_anchor.trim())
      .map((state) => ({ key: `${entity.id}:${state.id}`, entityId: entity.id, stateId: state.id, name: `${entity.name} — ${state.label}` })),
  ]);
}

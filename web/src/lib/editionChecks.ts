/**
 * Finish reports edition blockers as validator findings: a code, a technical
 * message and artifact ids. The Book room turns them into author-facing check
 * items — one per kind of problem, with each affected page listed once.
 */
import type { AppearanceState, FinishPreflight, InvariantFailure, StoryBible } from "../types/api";

export type CheckReview = "page" | "checks" | "lettering";

export interface FindingCopy {
  /** What went wrong, in the author's terms. */
  title: string;
  /** A one-page plan repair (POST /pages/{n}/replan) can clear it. */
  replannable?: boolean;
  /** What fixes it, or where it gets fixed. */
  fix: string;
  /** Which Pages view the page links open. */
  review: CheckReview;
}

/** Codes Finish emits (page_finishing.py); anything unknown keeps its own message. */
const COPY: Record<string, FindingCopy> = {
  cross_page_appearance_state: {
    title: "A character’s look is out of order",
    fix: "The page plan shows a look the story hasn’t changed into yet, so redrawing alone won’t clear it. Re-plan the page, then redraw it.",
    review: "page",
    replannable: true,
  },
  adaptation_lineage: {
    title: "The page plan is older than the book adaptation",
    fix: "The adaptation changed after these pages were planned. Plan the pages again from Pages.",
    review: "checks",
  },
  active_page_order: {
    title: "The page plan no longer includes this page version",
    fix: "Plan the pages again from Pages so the edition uses one page version.",
    review: "checks",
  },
  render_lineage: {
    title: "The page artwork can’t be traced to its drawing",
    fix: "Redraw the page from Pages. Other pages are unaffected.",
    review: "checks",
  },
  stale_page_render: {
    title: "The page artwork is older than its page plan",
    fix: "Open the page and redraw it from its current plan. The old art stays in the page’s history.",
    review: "page",
  },
  edition_model_mismatch: {
    title: "The page was drawn for a different page layout",
    fix: "Redraw the page from Pages.",
    review: "checks",
  },
  corrupt_page_render: {
    title: "The page image can’t be read",
    fix: "Redraw the page from Pages.",
    review: "checks",
  },
  page_render_dimensions: {
    title: "The page image is the wrong size",
    fix: "Redraw the page from Pages.",
    review: "checks",
  },
  open_draw_invariant: {
    title: "The page has open drawing problems",
    fix: "Resolve them in the page’s checks.",
    review: "checks",
  },
  open_upstream_invariant: {
    title: "The page has open story problems",
    fix: "Resolve them in the page’s checks.",
    review: "checks",
  },
  lettering_layout: {
    title: "The lettering layout needs a fix",
    fix: "Open Lettering to fix the layout. No artwork redraw is required.",
    review: "lettering",
  },
  production_geometry: {
    title: "The page doesn’t fit the print size",
    fix: "Open the page’s checks to see what can’t be kept within the page.",
    review: "checks",
  },
  production_normalization: {
    title: "The page can’t be prepared for print as drawn",
    fix: "Open the page’s checks to see what needs a creative fix.",
    review: "checks",
  },
  page_issue_lineage: {
    title: "The page’s review history is inconsistent",
    fix: "Open the page’s checks to review its issues again.",
    review: "checks",
  },
};

export interface FindingGroup {
  key: string;
  code: string;
  /** The stage whose artifact must change; only Plan-owned findings re-plan one page. */
  ownerStage: InvariantFailure["owner_stage"];
  copy: FindingCopy | null;
  /** The validator's own message, kept for unknown codes and evidence. */
  message: string;
  /** Book-level packaging findings carry no page. */
  pageNumbers: number[];
  evidence: string[];
  /** Characters, places or objects the finding cites, with the looks involved. */
  subjects: string[];
}

function subjectLabels(bible: StoryBible | undefined, finding: InvariantFailure): string[] {
  if (!bible) return [];
  const entities: Array<{ id: string; name: string; appearance_states?: AppearanceState[] }> = [
    ...bible.characters, ...bible.locations, ...(bible.props ?? []),
  ];
  // Artifact ids list the context (expected and cited looks); the evidence
  // quotes only the ids that are wrong, so it names the looks when it can.
  const quoted = new Set(finding.evidence.flatMap((line) => [...line.matchAll(/'([^']+)'/g)].map((match) => match[1])));
  const cited = new Set([...(finding.artifact_ids ?? []), ...quoted]);
  return entities.flatMap((entity) => {
    if (!cited.has(entity.id)) return [];
    const states = entity.appearance_states ?? [];
    const named = states.some((state) => quoted.has(state.id)) ? quoted : cited;
    const looks = states.filter((state) => named.has(state.id)).map((state) => `“${state.label}”`);
    return [looks.length ? `${entity.name} · ${looks.join(", ")}` : entity.name];
  });
}

/** One group per problem kind, so a finding repeated on a page or across pages reads once. */
export function groupEditionFindings(preflight: FinishPreflight | undefined, bible?: StoryBible): FindingGroup[] {
  if (!preflight) return [];
  const groups = new Map<string, FindingGroup>();
  const add = (finding: InvariantFailure, pageNumber: number | null) => {
    const copy = COPY[finding.code] ?? null;
    const key = `${pageNumber === null ? "book" : "pages"}:${finding.owner_stage}:${finding.code}:${copy ? "" : finding.message}`;
    const group = groups.get(key) ?? {
      key, code: finding.code, ownerStage: finding.owner_stage, copy, message: finding.message,
      pageNumbers: [], evidence: [], subjects: [],
    };
    if (pageNumber !== null && !group.pageNumbers.includes(pageNumber)) group.pageNumbers.push(pageNumber);
    group.evidence = [...new Set([...group.evidence, ...finding.evidence])];
    group.subjects = [...new Set([...group.subjects, ...subjectLabels(bible, finding)])];
    groups.set(key, group);
  };
  preflight.packaging_failures.forEach((finding) => add(finding, null));
  preflight.pages.forEach((page) => page.invariant_failures.forEach((finding) => add(finding, page.page_number)));
  return [...groups.values()];
}

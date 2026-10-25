import type { ComicPage } from "../types/api";

/** One opening of the book on the Pages table: a facing pair, a lone page or a double-wide page. */
export interface GallerySpread<T> {
  key: string;
  kind: "facing" | "wide";
  /** Facing openings always have two slots; an empty slot is the blank side of a lone page. */
  slots: Array<T | null>;
}

/**
 * Lay every planned page (drawn or not) out as the book opens. A `left` page
 * pairs with the `right` page that immediately follows it; any page that does
 * not pair sits on its own side, and the opening page of the book sits on the
 * right as a first page does.
 */
export function gallerySpreads<T extends { page: Pick<ComicPage, "page_number" | "spread_role"> }>(
  items: T[],
): GallerySpread<T>[] {
  const ordered = [...items].sort((a, b) => a.page.page_number - b.page.page_number);
  const spreads: GallerySpread<T>[] = [];
  for (let index = 0; index < ordered.length; index += 1) {
    const item = ordered[index];
    const next = ordered[index + 1];
    const number = item.page.page_number;
    const role = item.page.spread_role;
    if (role === "spread") {
      spreads.push({ key: `wide-${number}`, kind: "wide", slots: [item] });
      continue;
    }
    if (role === "left" && next?.page.spread_role === "right" && next.page.page_number === number + 1) {
      spreads.push({ key: `pair-${number}`, kind: "facing", slots: [item, next] });
      index += 1;
      continue;
    }
    const onRight = role === "right" || (role === "single" && index === 0);
    spreads.push({ key: `lone-${number}`, kind: "facing", slots: onRight ? [null, item] : [item, null] });
  }
  return spreads;
}

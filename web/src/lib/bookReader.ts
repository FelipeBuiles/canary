import type { CompletePagesResponse, ComicPage } from "../types/api";

export type SpreadRole = ComicPage["spread_role"];

export interface ReaderPage {
  pageNumber: number;
  revision: number;
  spreadRole: SpreadRole;
}

/**
 * A single thing the reader shows at once: one page, one double-wide page, or
 * two facing pages read as one image.
 */
export interface ReaderView {
  key: string;
  kind: "single" | "wide" | "facing";
  pages: ReaderPage[];
}

export type ReaderLayout = "spreads" | "single";

/**
 * Drawn pages in book order. A page with no active render has not been drawn
 * yet and is simply absent — the reader never shows gaps or placeholders.
 */
export function readerPages(data: CompletePagesResponse | undefined): ReaderPage[] {
  if (!data) return [];
  return data.pages
    .filter((item) => item.active_render !== null)
    .map((item) => ({
      pageNumber: item.page.page_number,
      revision: item.active_render!.render.revision,
      spreadRole: item.page.spread_role,
    }))
    .sort((a, b) => a.pageNumber - b.pageNumber);
}

/**
 * Group pages into what the reader shows per turn.
 *
 * Facing pairs only form when a `left` is immediately followed by its `right`;
 * Plan already enforces that ordering, but an undrawn page between them would
 * break the pair, and pairing across the gap would show a spread that does not
 * exist in the book.
 */
export function buildReaderViews(
  pages: ReaderPage[],
  layout: ReaderLayout,
): ReaderView[] {
  const views: ReaderView[] = [];
  for (let index = 0; index < pages.length; index += 1) {
    const page = pages[index];
    const next = pages[index + 1];
    const key = `page-${page.pageNumber}-rev-${page.revision}`;

    if (page.spreadRole === "spread") {
      views.push({ key, kind: "wide", pages: [page] });
      continue;
    }
    if (
      layout === "spreads"
      && page.spreadRole === "left"
      && next?.spreadRole === "right"
      && next.pageNumber === page.pageNumber + 1
    ) {
      views.push({ key, kind: "facing", pages: [page, next] });
      index += 1;
      continue;
    }
    views.push({ key, kind: "single", pages: [page] });
  }
  return views;
}

/** The view holding a page, so layout and mode switches keep the reader's place. */
export function viewIndexForPage(views: ReaderView[], pageNumber: number): number {
  const found = views.findIndex((view) =>
    view.pages.some((page) => page.pageNumber === pageNumber),
  );
  return found === -1 ? 0 : found;
}

/** "Page 4" or "Pages 4–5" — the label under the reader stage. */
export function viewLabel(
  view: ReaderView | undefined,
  singular: string,
  plural: string,
): string {
  if (!view) return "";
  if (view.pages.length === 1) return `${singular} ${view.pages[0].pageNumber}`;
  const first = view.pages[0].pageNumber;
  const last = view.pages[view.pages.length - 1].pageNumber;
  return `${plural} ${first}–${last}`;
}

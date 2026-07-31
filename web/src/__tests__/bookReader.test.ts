import { describe, expect, it } from "vitest";
import {
  buildReaderViews,
  readerPages,
  viewIndexForPage,
  viewLabel,
  type ReaderPage,
} from "../lib/bookReader";
import type { CompletePagesResponse } from "../types/api";

function page(
  pageNumber: number,
  spreadRole: ReaderPage["spreadRole"] = "single",
): ReaderPage {
  return { pageNumber, revision: 1, spreadRole };
}

describe("readerPages", () => {
  it("keeps only drawn pages, in book order, at their active revision", () => {
    const response = {
      pages: [
        { page: { page_number: 3, spread_role: "single" }, active_render: { render: { revision: 2 } } },
        { page: { page_number: 1, spread_role: "single" }, active_render: { render: { revision: 5 } } },
        { page: { page_number: 2, spread_role: "single" }, active_render: null },
      ],
    } as unknown as CompletePagesResponse;

    expect(readerPages(response)).toEqual([
      { pageNumber: 1, revision: 5, spreadRole: "single" },
      { pageNumber: 3, revision: 2, spreadRole: "single" },
    ]);
  });

  it("is empty before the pages query resolves", () => {
    expect(readerPages(undefined)).toEqual([]);
  });
});

describe("buildReaderViews", () => {
  it("pairs a left page with the right page that follows it", () => {
    const views = buildReaderViews(
      [page(1), page(2, "left"), page(3, "right"), page(4)],
      "spreads",
    );

    expect(views.map((view) => view.kind)).toEqual(["single", "facing", "single"]);
    expect(views[1].pages.map((item) => item.pageNumber)).toEqual([2, 3]);
  });

  it("does not pair across an undrawn page", () => {
    // Page 3 is missing, so pairing 2 with 4 would invent a spread.
    const views = buildReaderViews([page(2, "left"), page(4, "right")], "spreads");

    expect(views.map((view) => view.kind)).toEqual(["single", "single"]);
  });

  it("gives a double-wide page its own view in either layout", () => {
    for (const layout of ["spreads", "single"] as const) {
      const views = buildReaderViews([page(1), page(2, "spread"), page(3)], layout);
      expect(views.map((view) => view.kind)).toEqual(["single", "wide", "single"]);
    }
  });

  it("shows one page per view in single-page layout", () => {
    const views = buildReaderViews([page(1, "left"), page(2, "right")], "single");

    expect(views).toHaveLength(2);
    expect(views.every((view) => view.pages.length === 1)).toBe(true);
  });

  it("keys views by page and revision so a correction remounts the image", () => {
    const [before] = buildReaderViews([page(1)], "spreads");
    const [after] = buildReaderViews(
      [{ pageNumber: 1, revision: 2, spreadRole: "single" }],
      "spreads",
    );

    expect(before.key).not.toEqual(after.key);
  });
});

describe("viewIndexForPage", () => {
  it("finds the view holding a page, including the right half of a spread", () => {
    const views = buildReaderViews([page(1), page(2, "left"), page(3, "right")], "spreads");

    expect(viewIndexForPage(views, 1)).toBe(0);
    expect(viewIndexForPage(views, 3)).toBe(1);
  });

  it("falls back to the first view for a page that is not shown", () => {
    expect(viewIndexForPage(buildReaderViews([page(1)], "spreads"), 99)).toBe(0);
  });
});

describe("viewLabel", () => {
  it("labels a single page and a facing pair", () => {
    const views = buildReaderViews([page(1), page(2, "left"), page(3, "right")], "spreads");

    expect(viewLabel(views[0], "Page", "Pages")).toBe("Page 1");
    expect(viewLabel(views[1], "Page", "Pages")).toBe("Pages 2–3");
    expect(viewLabel(undefined, "Page", "Pages")).toBe("");
  });
});

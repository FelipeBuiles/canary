import { describe, expect, it } from "vitest";
import { gallerySpreads } from "../lib/pageSpreads";
import type { ComicPage } from "../types/api";

const page = (page_number: number, spread_role: ComicPage["spread_role"]) => ({ page: { page_number, spread_role } });
const shape = (items: ReturnType<typeof page>[]) =>
  gallerySpreads(items).map((spread) => spread.slots.map((slot) => slot?.page.page_number ?? null));

describe("gallerySpreads", () => {
  it("opens on the right, pairs facing pages and closes on the left", () => {
    expect(shape([page(1, "single"), page(2, "left"), page(3, "right"), page(4, "single")]))
      .toEqual([[null, 1], [2, 3], [4, null]]);
  });

  it("keeps an unpaired page on its own side instead of pairing across a gap", () => {
    expect(shape([page(2, "left"), page(4, "right")])).toEqual([[2, null], [null, 4]]);
  });

  it("gives a double-wide page its own opening", () => {
    const spreads = gallerySpreads([page(5, "spread")]);
    expect(spreads[0].kind).toBe("wide");
    expect(spreads[0].slots.map((slot) => slot?.page.page_number)).toEqual([5]);
  });

  it("orders pages by number whatever order they arrive in", () => {
    expect(shape([page(3, "right"), page(2, "left")])).toEqual([[2, 3]]);
  });
});

import { describe, it, expect } from "vitest";
import {
  browseStories,
  deriveGenres,
  genreLabel,
  SORT_OPTIONS,
} from "../lib/storyBrowser";
import type { ShortStory } from "../types/api";

const make = (o: Partial<ShortStory> & { code: string }): ShortStory => ({
  title: o.code,
  author: "Anon",
  words: 1000,
  genres: [],
  ...o,
});

describe("deriveGenres", () => {
  it("returns unique genres ordered by frequency, ties alphabetical", () => {
    const stories = [
      make({ code: "a", genres: ["horror", "sci-fi"] }),
      make({ code: "b", genres: ["horror"] }),
      make({ code: "c", genres: ["sci-fi", "fantasy"] }),
    ];
    // horror x2, sci-fi x2 (tie → alpha: horror < sci-fi), fantasy x1
    expect(deriveGenres(stories)).toEqual(["horror", "sci-fi", "fantasy"]);
  });

  it("handles an empty catalog", () => {
    expect(deriveGenres([])).toEqual([]);
  });
});

describe("browseStories — filtering", () => {
  const stories = [
    make({ code: "a", title: "Alpha", author: "Poe", genres: ["horror"], rating: 5, words: 500 }),
    make({ code: "b", title: "Beta", author: "Verne", genres: ["sci-fi"], rating: 3, words: 2000 }),
    make({ code: "c", title: "Gamma", author: "Poe", genres: ["horror", "mystery"], words: 100 }),
  ];

  it("filters genres with OR semantics", () => {
    const r = browseStories(stories, { search: "", genres: ["sci-fi", "mystery"], sort: "title" });
    expect(r.map((s) => s.code)).toEqual(["b", "c"]);
  });

  it("combines search AND genre", () => {
    // author Poe (a, c) AND genre horror (a, c) → both
    const r = browseStories(stories, { search: "poe", genres: ["horror"], sort: "title" });
    expect(r.map((s) => s.code)).toEqual(["a", "c"]);
  });

  it("search matches title, author, or genre substrings", () => {
    expect(browseStories(stories, { search: "myst", genres: [], sort: "title" }).map((s) => s.code)).toEqual(["c"]);
    expect(browseStories(stories, { search: "verne", genres: [], sort: "title" }).map((s) => s.code)).toEqual(["b"]);
    expect(browseStories(stories, { search: "alph", genres: [], sort: "title" }).map((s) => s.code)).toEqual(["a"]);
  });

  it("returns everything when no filters are set", () => {
    expect(browseStories(stories, { search: "  ", genres: [], sort: "title" })).toHaveLength(3);
  });

  it("does not mutate the input array", () => {
    const order = stories.map((s) => s.code);
    browseStories(stories, { search: "", genres: [], sort: "shortest" });
    expect(stories.map((s) => s.code)).toEqual(order);
  });
});

describe("browseStories — sorting", () => {
  // Two 5★ stories whose word-length and title order disagree, so
  // "recommended" (ties → shortest) and "top_rated" (ties → title) diverge.
  const stories = [
    make({ code: "r5_long_A", title: "Avalon", rating: 5, words: 900, publish_year: 1850 }),
    make({ code: "r5_short_Z", title: "Zephyr", rating: 5, words: 150, publish_year: 1980 }),
    make({ code: "r3", title: "Marlow", rating: 3, words: 100, publish_year: 1900 }),
    make({ code: "unrated", title: "Drift", words: 50 }), // no rating, no year
  ];
  const order = (sort: Parameters<typeof browseStories>[1]["sort"]) =>
    browseStories(stories, { search: "", genres: [], sort }).map((s) => s.code);

  it("recommended: rating desc, unrated last, ties → shortest", () => {
    expect(order("recommended")).toEqual(["r5_short_Z", "r5_long_A", "r3", "unrated"]);
  });

  it("top_rated: rating desc, unrated last, ties → title", () => {
    expect(order("top_rated")).toEqual(["r5_long_A", "r5_short_Z", "r3", "unrated"]);
  });

  it("shortest: fewest words first", () => {
    expect(order("shortest")).toEqual(["unrated", "r3", "r5_short_Z", "r5_long_A"]);
  });

  it("title: alphabetical", () => {
    expect(order("title")).toEqual(["r5_long_A", "unrated", "r3", "r5_short_Z"]); // Avalon, Drift, Marlow, Zephyr
  });

  it("year: newest first, missing year last", () => {
    expect(order("year")).toEqual(["r5_short_Z", "r3", "r5_long_A", "unrated"]); // 1980, 1900, 1850, none
  });
});

describe("genreLabel", () => {
  it("formats slugs for display", () => {
    expect(genreLabel("horror")).toBe("Horror");
    expect(genreLabel("sci-fi")).toBe("Sci-Fi");
    expect(genreLabel("childrens")).toBe("Children's");
  });
});

describe("SORT_OPTIONS", () => {
  it("leads with the recommended default", () => {
    expect(SORT_OPTIONS[0].value).toBe("recommended");
  });
});

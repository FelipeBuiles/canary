import { describe, it, expect } from "vitest";
import { browseStories, deriveGenres, genreLabel, SORT_OPTIONS } from "../lib/storyBrowser";
import type { ShortStory } from "../types/api";

const make = (o: Partial<ShortStory> & { code: string }): ShortStory => ({
  title: o.code,
  author: "Anon",
  words: 1000,
  genres: [],
  ...o,
});

const stories = [
  make({ code: "kaitlin", title: "Kaitlin Out of Space", author: "Krishan Coupland", words: 3000, genres: ["sci-fi", "drama"], description: "A quiet alien story" }),
  make({ code: "sea", title: "The Sea in Me", author: "Krishan Coupland", words: 2800, genres: ["drama"], description: "An athlete and her mother" }),
  make({ code: "education", title: "An Education", author: "Angie", words: 900, genres: ["fantasy", "dialogue"], description: "A curious student" }),
  make({ code: "cats", title: "The Cats of Ulthar", author: "H. P. Lovecraft", words: 1341, genres: ["gothic", "horror"], source_kind: "archive", publish_year: 1920 }),
];

const browse = (search: string, genres: string[] = [], sort: Parameters<typeof browseStories>[1]["sort"] = "relevance") =>
  browseStories(stories, { search, genres, sort }).map((story) => story.code);

describe("sample story browsing", () => {
  it("keeps editorial order for an empty relevance query and does not mutate it", () => {
    expect(browse(" ")).toEqual(["kaitlin", "sea", "education", "cats"]);
    expect(stories.map((story) => story.code)).toEqual(["kaitlin", "sea", "education", "cats"]);
  });

  it("ranks title matches before descriptions and requires every search term", () => {
    expect(browse("sea")).toEqual(["sea"]);
    expect(browse("quiet alien")).toEqual(["kaitlin"]);
    expect(browse("krishan drama")).toEqual(["kaitlin", "sea"]);
    expect(browse("missing")).toEqual([]);
  });

  it("matches author, tags, and descriptions with genre filters", () => {
    expect(browse("angie")).toEqual(["education"]);
    expect(browse("lovecraft")).toEqual(["cats"]);
    expect(browse("fantasy")).toEqual(["education"]);
    expect(browse("mother")).toEqual(["sea"]);
    expect(browse("", ["fantasy", "sci-fi"])).toEqual(["kaitlin", "education"]);
    expect(browse("krishan", ["fantasy"])).toEqual([]);
  });

  it("offers meaningful length and title sorts", () => {
    expect(browse("", [], "shortest")).toEqual(["education", "cats", "sea", "kaitlin"]);
    expect(browse("", [], "longest")).toEqual(["kaitlin", "sea", "cats", "education"]);
    expect(browse("", [], "title")).toEqual(["education", "kaitlin", "cats", "sea"]);
    expect(SORT_OPTIONS[0].value).toBe("relevance");
  });

  it("keeps classics in the main results while allowing collection filters", () => {
    expect(browseStories(stories, { search: "", genres: [], sort: "relevance", source: "archive" }).map((story) => story.code)).toEqual(["cats"]);
    expect(browseStories(stories, { search: "", genres: [], sort: "relevance", source: "curated" }).map((story) => story.code)).toEqual(["kaitlin", "sea", "education"]);
  });

  it("derives tags from the catalog", () => {
    expect(deriveGenres(stories)).toEqual(["drama", "dialogue", "fantasy", "gothic", "horror", "sci-fi"]);
    expect(deriveGenres([])).toEqual([]);
    expect(genreLabel("sci-fi")).toBe("Sci-Fi");
    expect(genreLabel("coming-of-age")).toBe("Coming of age");
  });
});

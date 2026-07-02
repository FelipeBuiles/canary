import type { ShortStory } from "../types/api";

export type SortKey = "recommended" | "top_rated" | "shortest" | "title" | "year";

export interface SortOption {
  value: SortKey;
  /** English source label; the component runs it through t() for display. */
  label: string;
}

/** Order of the sort dropdown. Recommended leads as the default ordering. */
export const SORT_OPTIONS: SortOption[] = [
  { value: "recommended", label: "Recommended" },
  { value: "top_rated", label: "Top-rated" },
  { value: "shortest", label: "Shortest" },
  { value: "title", label: "Title (A–Z)" },
  { value: "year", label: "Year (newest)" },
];

/**
 * Unique genres present in the catalog, ordered by frequency (most common
 * first) so the meatiest facets lead the chip row. Derived from the data
 * rather than hardcoded, so it can't drift from the upstream source. Ties
 * break alphabetically for stable output.
 */
export function deriveGenres(stories: ShortStory[]): string[] {
  const counts = new Map<string, number>();
  for (const story of stories) {
    for (const genre of story.genres ?? []) {
      counts.set(genre, (counts.get(genre) ?? 0) + 1);
    }
  }
  return [...counts.keys()].sort((a, b) => {
    const byCount = (counts.get(b) ?? 0) - (counts.get(a) ?? 0);
    return byCount !== 0 ? byCount : a.localeCompare(b);
  });
}

const GENRE_LABEL_OVERRIDES: Record<string, string> = {
  "sci-fi": "Sci-Fi",
  childrens: "Children's",
};

/** Pretty display for a raw genre slug: "war" -> "War", "sci-fi" -> "Sci-Fi". */
export function genreLabel(genre: string): string {
  return (
    GENRE_LABEL_OVERRIDES[genre] ??
    genre
      .split(/[\s-]+/)
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ")
  );
}

export interface BrowseParams {
  search: string;
  genres: string[];
  sort: SortKey;
}

/**
 * Rank used by the rating-led sorts: higher rating first, with unrated
 * stories collapsing to a sentinel below every real rating so they sink last.
 */
function ratingRank(story: ShortStory): number {
  return typeof story.rating === "number" ? story.rating : -1;
}

const COMPARATORS: Record<SortKey, (a: ShortStory, b: ShortStory) => number> = {
  // Top-rated first; among equal ratings, the quickest to try; unrated last.
  recommended: (a, b) =>
    ratingRank(b) - ratingRank(a) || a.words - b.words || a.title.localeCompare(b.title),
  // Pure rating, unrated last, ties broken by title.
  top_rated: (a, b) => ratingRank(b) - ratingRank(a) || a.title.localeCompare(b.title),
  shortest: (a, b) => a.words - b.words || a.title.localeCompare(b.title),
  title: (a, b) => a.title.localeCompare(b.title),
  // Newest first; stories without a publish year sink to the bottom.
  year: (a, b) =>
    (b.publish_year ?? -Infinity) - (a.publish_year ?? -Infinity) ||
    a.title.localeCompare(b.title),
};

/**
 * Filter then sort the catalog. Search matches title/author/genre substrings;
 * genres filter with OR semantics (a story shows if it matches any selected
 * genre) and AND against the search. Pure — returns a new array and never
 * mutates the input.
 */
export function browseStories(
  stories: ShortStory[],
  { search, genres, sort }: BrowseParams,
): ShortStory[] {
  const query = search.trim().toLowerCase();
  const genreSet = genres.length ? new Set(genres) : null;

  const filtered = stories.filter((story) => {
    if (genreSet && !(story.genres ?? []).some((genre) => genreSet.has(genre))) {
      return false;
    }
    if (!query) return true;
    return (
      story.title.toLowerCase().includes(query) ||
      story.author.toLowerCase().includes(query) ||
      (story.genres ?? []).some((genre) => genre.toLowerCase().includes(query))
    );
  });

  return filtered.sort(COMPARATORS[sort]);
}

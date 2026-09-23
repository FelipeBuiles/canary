import type { ShortStory } from "../types/api";

export type SortKey = "relevance" | "shortest" | "longest" | "title";

export const SORT_OPTIONS: { value: SortKey; label: string }[] = [
  { value: "relevance", label: "Best match" },
  { value: "shortest", label: "Shortest first" },
  { value: "longest", label: "Longest first" },
  { value: "title", label: "Title (A–Z)" },
];

/** Tags come from the shipped catalog, so a new story can add a facet without UI edits. */
export function deriveGenres(stories: ShortStory[]): string[] {
  const counts = new Map<string, number>();
  for (const story of stories) {
    for (const genre of story.genres ?? []) {
      counts.set(genre, (counts.get(genre) ?? 0) + 1);
    }
  }
  return [...counts.keys()].sort((a, b) =>
    (counts.get(b) ?? 0) - (counts.get(a) ?? 0) || a.localeCompare(b),
  );
}

const GENRE_LABEL_OVERRIDES: Record<string, string> = {
  "sci-fi": "Sci-Fi",
  "coming-of-age": "Coming of age",
};

export function genreLabel(genre: string): string {
  return GENRE_LABEL_OVERRIDES[genre] ?? genre
    .split(/[\s-]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export interface BrowseParams {
  search: string;
  genres: string[];
  sort: SortKey;
  source?: "all" | "curated" | "archive";
}

function searchScore(story: ShortStory, terms: string[]): number {
  if (!terms.length) return 0;
  const title = story.title.toLocaleLowerCase();
  const author = story.author.toLocaleLowerCase();
  const genres = (story.genres ?? []).join(" ").toLocaleLowerCase();
  const description = `${story.description ?? ""} ${story.showcase_note ?? ""} ${story.publish_source ?? ""} ${story.publish_year ?? ""}`.toLocaleLowerCase();
  let score = 0;
  for (const term of terms) {
    if (title === term) score += 10;
    else if (title.includes(term)) score += 6;
    else if (author.includes(term)) score += 4;
    else if (genres.includes(term)) score += 3;
    else if (description.includes(term)) score += 1;
    else return -1;
  }
  return score;
}

/** Match every search term, then rank direct title hits ahead of broader matches. */
export function browseStories(stories: ShortStory[], { search, genres, sort, source = "all" }: BrowseParams): ShortStory[] {
  const terms = search.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  const genreSet = new Set(genres);
  return stories
    .map((story, index) => ({ story, index, score: searchScore(story, terms) }))
    .filter(({ story, score }) => score >= 0 && (source === "all" || (story.source_kind ?? "curated") === source) && (
      genreSet.size === 0 || (story.genres ?? []).some((genre) => genreSet.has(genre))
    ))
    .sort((a, b) => {
      if (sort === "shortest") return a.story.words - b.story.words || a.index - b.index;
      if (sort === "longest") return b.story.words - a.story.words || a.index - b.index;
      if (sort === "title") return a.story.title.localeCompare(b.story.title) || a.index - b.index;
      return b.score - a.score || a.index - b.index;
    })
    .map(({ story }) => story);
}

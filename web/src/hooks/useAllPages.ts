import { useQueries } from "@tanstack/react-query";
import { getPage } from "../api/pages";
import type { ComicPage, PageSummary } from "../types/api";

export function useAllPages(
  project: string | undefined,
  summaries: PageSummary[] | undefined,
): { pages: (ComicPage | undefined)[]; isLoading: boolean } {
  const results = useQueries({
    queries: (summaries ?? []).map((s) => ({
      queryKey: ["project", project, "pages", s.page_number],
      queryFn: () => getPage(project!, s.page_number),
      enabled: !!project && !!summaries,
      staleTime: 5 * 60 * 1000,
    })),
  });

  return {
    pages: results.map((r) => r.data),
    isLoading: results.some((r) => r.isLoading),
  };
}

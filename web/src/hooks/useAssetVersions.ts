import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { projectPath, seriesPath } from "../api/projectScope";
import { setAssetVersions } from "../lib/assetVersions";
import { subscribe as subscribeImageTokens } from "../lib/imageRefresh";

function useScopeVersions(scopePath: string | null) {
  return useQuery({
    queryKey: ["asset-versions", scopePath],
    // The listing lands in the store before React sees it, so the first
    // render of a room already builds cacheable URLs (no second download).
    queryFn: async () => {
      const { versions } = await apiFetch<{ versions: Record<string, string> }>(`${scopePath}/asset-versions`);
      setAssetVersions(`/api${scopePath}`, versions);
      return versions;
    },
    enabled: !!scopePath,
    staleTime: Infinity,
    refetchOnWindowFocus: "always",
    retry: false,
  });
}

/**
 * Keep the project's image versions current; true once rooms may render.
 * A redraw landing or any status change (a run finishing) refreshes the
 * listing. A failed listing only means images revalidate, so it never blocks.
 */
export function useAssetVersions(key: string | undefined, statusStamp: unknown): boolean {
  const qc = useQueryClient();
  const series = key ? seriesPath(key) : null;
  const part = key && projectPath(key) !== series ? projectPath(key) : null;
  const seriesVersions = useScopeVersions(series);
  const partVersions = useScopeVersions(part);

  // The first status only confirms the listing already being fetched.
  const seenStamp = useRef<{ key?: string; stamp?: unknown }>({});
  useEffect(() => {
    const seen = seenStamp.current;
    seenStamp.current = { key, stamp: statusStamp };
    if (!key || seen.key !== key || seen.stamp === undefined) return;
    void qc.invalidateQueries({ queryKey: ["asset-versions"] }, { cancelRefetch: false });
  }, [key, qc, statusStamp]);

  useEffect(() => {
    let scheduled = false;
    return subscribeImageTokens(() => {
      if (scheduled) return;
      scheduled = true;
      queueMicrotask(() => {
        scheduled = false;
        void qc.invalidateQueries({ queryKey: ["asset-versions"] }, { cancelRefetch: false });
      });
    });
  }, [qc]);

  const settled = (query: { isFetched: boolean; isError: boolean }, scope: string | null) =>
    !scope || query.isFetched || query.isError;
  return settled(seriesVersions, series) && settled(partVersions, part);
}

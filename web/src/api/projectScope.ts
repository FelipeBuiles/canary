import type { QueryClient } from "@tanstack/react-query";
import { versionedUrl } from "../lib/assetVersions";

/**
 * A project key names a whole project (`<id>`) or one of its parts
 * (`<id>~<part>`). Page work — Extract through Finish, pages and exports —
 * belongs to a part; Look work — Style, Cast and the Story Bible — belongs to
 * the series. Query caches key on the project key, so each part keeps its own.
 */
const SEPARATOR = "~";

export function partProjectKey(id: string, part: string | null | undefined): string {
  return part ? `${id}${SEPARATOR}${part}` : id;
}

export function splitProjectKey(key: string): { id: string; part: string | null } {
  const index = key.indexOf(SEPARATOR);
  return index < 0 ? { id: key, part: null } : { id: key.slice(0, index), part: key.slice(index + 1) || null };
}

/** The series root's API path: Style, Cast, the Story Bible, parts and config. */
export function seriesPath(key: string): string {
  return `/projects/${encodeURIComponent(splitProjectKey(key).id)}`;
}

/** The part's API path when the key names one; otherwise the series root. */
export function projectPath(key: string): string {
  const { id, part } = splitProjectKey(key);
  const base = `/projects/${encodeURIComponent(id)}`;
  return part ? `${base}/parts/${encodeURIComponent(part)}` : base;
}

/** The same room for another project key: `/project/<key>/<room>`. */
export function withProjectKey(pathname: string, key: string): string {
  const segments = pathname.split("/");
  const index = segments.indexOf("project");
  if (index < 0 || index + 1 >= segments.length) return pathname;
  segments[index + 1] = encodeURIComponent(key);
  return segments.join("/");
}

/** A file in the series root (references, plates, Style proofs). */
export function seriesFileUrl(key: string, relativePath: string): string {
  return versionedUrl(`/api${seriesPath(key)}/files/${relativePath}`);
}

/** A file in the part (page renders, the part's cover). */
export function projectFileUrl(key: string, relativePath: string): string {
  return versionedUrl(`/api${projectPath(key)}/files/${relativePath}`);
}

/**
 * Invalidate one resource for every part of a project. Series edits (Style,
 * Cast, the Story Bible) change what every part shows, and a part's change
 * can reopen series stages, so refreshing all scopes keeps every view honest.
 */
export function invalidateProject(qc: QueryClient, key: string | undefined, ...rest: unknown[]) {
  if (!key) return Promise.resolve();
  const { id } = splitProjectKey(key);
  return qc.invalidateQueries({
    predicate: (query) => {
      const [head, scope, ...tail] = query.queryKey;
      return head === "project" && typeof scope === "string" && splitProjectKey(scope).id === id
        && rest.every((segment, index) => Object.is(tail[index], segment)
          || JSON.stringify(tail[index]) === JSON.stringify(segment));
    },
  });
}

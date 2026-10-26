/**
 * Content versions for project images, so their URLs can be cached for good.
 *
 * The server lists every image in a scope (`/asset-versions`) with a token
 * derived from its bytes. An image URL carrying its current token (`?v=`) is
 * served `immutable`: the browser shows its copy without asking again, across
 * room changes and reloads. A redraw changes the token, hence the URL. A URL
 * whose token is unknown or outdated is served as before and revalidates, so a
 * stale listing can cost a request but never shows the wrong image.
 */
const versionsByScope = new Map<string, Record<string, string>>();

/** Replace one scope's listing; `scope` is its URL base, e.g. `/api/projects/x`. */
export function setAssetVersions(scope: string, versions: Record<string, string>) {
  versionsByScope.set(scope, versions);
}

export function hasAssetVersions(scope: string) {
  return versionsByScope.has(scope);
}

/** Test-only reset between cases. */
export function resetAssetVersions() {
  versionsByScope.clear();
}

const FILE = /^(\/api\/projects\/[^/?]+(?:\/parts\/[^/?]+)?)\/(?:files|thumbnails\/[^/?]+)\/([^?]+)$/;
const RENDER = /^(\/api\/projects\/[^/?]+(?:\/parts\/[^/?]+)?)\/pages\/(\d+)\/renders\/(\d+)(?:\/preview\/[^/?]+)?$/;

function versionFor(path: string): string | undefined {
  const file = FILE.exec(path);
  if (file) {
    try {
      return versionsByScope.get(file[1])?.[decodeURIComponent(file[2])];
    } catch {
      return undefined;
    }
  }
  const render = RENDER.exec(path);
  if (render) {
    const pad = (value: string) => value.padStart(3, "0");
    return versionsByScope.get(render[1])?.[`draw/pages/page_${pad(render[2])}/render_${pad(render[3])}.png`];
  }
  return undefined;
}

/** `url` with its image's current version, or unchanged when none is known. */
export function versionedUrl(url: string): string {
  const [path, query = ""] = url.split("?", 2);
  const version = versionFor(path);
  if (!version) return url;
  const params = new URLSearchParams(query);
  params.set("v", version);
  return `${path}?${params.toString()}`;
}

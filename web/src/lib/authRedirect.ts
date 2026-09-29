/** Production auth links always return to the public domain, including from Fly. */
export function authRedirectUrl(path: string, origin = window.location.origin): string {
  const hostname = new URL(origin).hostname;
  const productionHosts = ["scenewright.ink", "www.scenewright.ink", "canary-web.fly.dev"];
  const base = productionHosts.includes(hostname) ? "https://scenewright.ink" : origin;
  return `${base}${path}`;
}

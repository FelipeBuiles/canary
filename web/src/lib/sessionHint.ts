/**
 * A non-secret "this browser has a Scenewright session" hint. The server uses
 * it only to choose which document to send for `/` (app shell vs. the public
 * homepage), so signed-in readers never see the marketing page flash first.
 * It grants nothing; authorization stays with the Supabase session.
 */
export const SESSION_HINT_COOKIE = "sw_signed_in";

export function hasSessionHint(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie.split("; ").some((item) => item === `${SESSION_HINT_COOKIE}=1`);
}

export function setSessionHint(signedIn: boolean): void {
  if (typeof document === "undefined" || signedIn === hasSessionHint()) return;
  const secure = window.location.protocol === "https:" ? "; Secure" : "";
  // Supabase refresh tokens outlive the short HttpOnly access cookie; the hint
  // follows the browser session and is cleared whenever it ends.
  document.cookie = `${SESSION_HINT_COOKIE}=${signedIn ? "1" : ""}; Path=/; SameSite=Lax; Max-Age=${signedIn ? 34_560_000 : 0}${secure}`;
}

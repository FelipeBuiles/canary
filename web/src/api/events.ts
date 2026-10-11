import { apiFetch } from "./client";
import { splitProjectKey } from "./projectScope";

export type WebProductEventName =
  | "page_viewed"
  | "station_viewed"
  | "inspect_drawer_opened"
  | "checkout_cancelled";

export async function trackProductEvent(
  eventName: WebProductEventName,
  options: { projectId?: string; properties?: Record<string, string | number | boolean | null> } = {},
): Promise<void> {
  try {
    await apiFetch<{ status: "accepted" }>("/events", {
      method: "POST",
      body: JSON.stringify({
        event_name: eventName,
        // Events describe the project; a part key names the same project.
        project_id: options.projectId ? splitProjectKey(options.projectId).id : options.projectId,
        properties: options.properties ?? {},
      }),
    });
  } catch {
    // Product analytics is best-effort and must never interrupt the UI.
  }
}

/** Observe authenticated account usage; this does not assert a signup occurred. */
export async function recordAccountSeen(): Promise<void> {
  try {
    await apiFetch<{ status: "accepted" }>("/events/account", { method: "POST" });
  } catch {
    // Best-effort, like other product analytics.
  }
}

/** Called only after GA4 loads with consent; the server verifies a new signup. */
export async function claimGa4Signup(): Promise<boolean> {
  try {
    const result = await apiFetch<{ signup: boolean }>("/events/ga4-signup", { method: "POST" });
    return result.signup === true;
  } catch { return false; }
}

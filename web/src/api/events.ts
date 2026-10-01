import { apiFetch } from "./client";

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
        project_id: options.projectId,
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

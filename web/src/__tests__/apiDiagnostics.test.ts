import { afterEach, expect, it, vi } from "vitest";
import { apiFetch, ApiError, isNetworkError } from "../api/client";
import { observeApiRequests } from "../lib/telemetryDiagnostics";
import { clearAccountRequests } from "../lib/accountEpoch";

vi.mock("../lib/supabase", () => ({ supabase: { auth: { getSession: async () => ({ data: { session: null } }) } } }));
vi.mock("../api/paidAction", () => ({ pendingAction: vi.fn(async () => null) }));
afterEach(() => vi.unstubAllGlobals());

it("joins the actual API response and error to its bounded browser context", async () => {
  const events = vi.fn();
  observeApiRequests(events, () => "01234567-89ab-4cde-89ab-0123456789ab");
  const fetcher = vi.fn(async (_url: unknown, options: RequestInit) => {
    const headers = options.headers as Record<string, string>;
    expect(headers.traceparent).toMatch(/^00-[a-f0-9]{32}-[a-f0-9]{16}-01$/);
    expect(headers["X-Canary-Session-ID"]).toBe("01234567-89ab-4cde-89ab-0123456789ab");
    return new Response(JSON.stringify({ detail: { code: "draw_preflight_rejected", message: "PRIVATE MANUSCRIPT" } }),
      { status: 409, headers: { "X-Request-ID": headers["X-Request-ID"] } });
  });
  vi.stubGlobal("fetch", fetcher);
  const error = await apiFetch("/projects/PRIVATE_ID/run?stage=draw", { method: "POST" }).catch(error => error);
  expect(error).toBeInstanceOf(ApiError);
  if (!(error instanceof ApiError)) throw error;
  expect(error.diagnostics).toMatchObject({ route: "/api/projects/:id/run", http_status: 409, error_code: "draw_preflight_rejected", outcome: "failed" });
  expect(events).toHaveBeenCalledOnce();
  expect(JSON.stringify(events.mock.calls)).not.toMatch(/PRIVATE_ID|PRIVATE MANUSCRIPT|stage=draw/);
});

it("keeps successful calls working when the telemetry observer fails", async () => {
  observeApiRequests(() => { throw new Error("export failed"); }, () => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true }) })));
  await expect(apiFetch("/account")).resolves.toEqual({ ok: true });
});

it("drops late responses after the account changes", async () => {
  const events = vi.fn();
  observeApiRequests(events, () => undefined);
  vi.stubGlobal("fetch", vi.fn(async () => {
    clearAccountRequests("other-account");
    return new Response('{"ok":true}', { status: 200 });
  }));
  await expect(apiFetch("/account")).rejects.toMatchObject({ name: "AbortError" });
  expect(events).not.toHaveBeenCalled();
});

it("marks a request with no response as a network error, but not a server error", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
  const dropped = await apiFetch("/projects/book/styles/suggest-estimate").catch(error => error);
  expect(isNetworkError(dropped)).toBe(true);
  vi.stubGlobal("fetch", vi.fn(async () => new Response("down", { status: 503 })));
  const failed = await apiFetch("/projects/book/styles/suggest-estimate").catch(error => error);
  expect(isNetworkError(failed)).toBe(false);
  expect(isNetworkError(new TypeError("Cannot read properties of undefined"))).toBe(false);
});

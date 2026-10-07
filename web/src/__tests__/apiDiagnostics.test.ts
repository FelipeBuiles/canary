import { afterEach, expect, it, vi } from "vitest";
import { apiFetch, ApiError } from "../api/client";
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

it("displays a readable storage message while retaining the rejection code for diagnostics", async () => {
  observeApiRequests(() => {}, () => undefined);
  const message = "Account storage is full. Delete projects you no longer need from their settings, then try again.";
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ detail: {
    code: "storage_budget_exceeded", message, admitted: false,
    used_bytes: 7991982797, limit_bytes: 5368709120, remaining_bytes: 0,
  } }), { status: 413 })));
  const error = await apiFetch("/projects/book/run?stage=draw", { method: "POST" }).catch(error => error);
  if (!(error instanceof ApiError)) throw error;
  expect(error).toMatchObject({ message, status: 413, code: "storage_budget_exceeded" });
  expect(error.diagnostics).toMatchObject({ http_status: 413, error_code: "storage_budget_exceeded" });
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

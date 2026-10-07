import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { webcrypto } from "node:crypto";
import { MutationObserver } from "@tanstack/react-query";
import { apiFetch } from "../api/client";
import { createAccountQueryClient } from "../api/queryClient";
import { clearAccountRequests } from "../lib/accountEpoch";

const auth = vi.hoisted(() => ({ id: "account-a" }));
vi.mock("../lib/supabase", () => ({ supabase: { auth: {
  getSession: async () => ({ data: { session: { access_token: auth.id, user: { id: auth.id } } } }),
} } }));

beforeEach(() => {
  vi.stubGlobal("crypto", webcrypto);
  localStorage.clear();
  auth.id = "account-a";
});
afterEach(() => { vi.unstubAllGlobals(); });

describe("paid action receipts", () => {
  it.each([
    "Page 6 requires 6 approved references, but this edition supports 5. Replan this page before drawing; identity references will not be silently dropped.",
    { code: "draw_preflight_rejected", message: "Reference sheet exceeds the pixel budget" },
  ])("releases a definite Draw rejection without automatically resubmitting: %j", async (detail) => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new TypeError("Connection lost"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail }), {
        status: 409, headers: { "Idempotency-Replayed": "true" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "started", stage: "draw" })));
    vi.stubGlobal("fetch", fetcher);
    const send = () => apiFetch("/projects/demo/run?stage=draw", { paidAction: true, method: "POST" });
    await expect(send()).rejects.toThrow("Connection lost");
    await expect(send()).rejects.toThrow("API 409");
    expect(fetcher).toHaveBeenCalledTimes(2);
    await expect(send()).resolves.toMatchObject({ status: "started" });
    const keys = fetcher.mock.calls.map((call) => call[1].headers["Idempotency-Key"]);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("releases a replayed Adapt approval rejection for the next explicit attempt", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new TypeError("Connection lost"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Adapt requires an approved adaptation brief" }), {
        status: 409, headers: { "Idempotency-Replayed": "true" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "started", stage: "adapt" })));
    vi.stubGlobal("fetch", fetcher);
    const send = () => apiFetch("/projects/demo/run?stage=adapt", { paidAction: true, method: "POST" });
    await expect(send()).rejects.toThrow("Connection lost");
    await expect(send()).rejects.toThrow("Adapt requires an approved adaptation brief");
    expect(fetcher).toHaveBeenCalledTimes(2); // No automatic paid retry.
    await expect(send()).resolves.toMatchObject({ status: "started" });
    const keys = fetcher.mock.calls.map((call) => call[1].headers["Idempotency-Key"]);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it.each([
    { code: "idempotency_indeterminate", message: "This action may have been accepted." },
    "Unknown draw conflict",
  ])("retains uncertain Draw receipts: %j", async (detail) => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(
      new Response(JSON.stringify({ detail }), { status: 409 }),
    ));
    vi.stubGlobal("fetch", fetcher);
    const send = () => apiFetch("/projects/demo/run?stage=draw", { paidAction: true, method: "POST" });
    await expect(send()).rejects.toThrow("API 409");
    await expect(send()).rejects.toThrow("API 409");
    expect(fetcher.mock.calls[1][1].headers["Idempotency-Key"])
      .toBe(fetcher.mock.calls[0][1].headers["Idempotency-Key"]);
  });

  it("does not retry a lost response; an explicit reattempt after navigation reuses its receipt", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("Connection lost"))
      .mockResolvedValue(new Response(JSON.stringify({ job: { id: "accepted" } }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const client = createAccountQueryClient(auth.id);
    const firstObserver = new MutationObserver(client, {
      mutationFn: () => apiFetch("/projects/demo/regen-ref?char_id=one", { paidAction: true, method: "POST" }),
    });
    await expect(firstObserver.mutate()).rejects.toThrow("Connection lost");
    expect(fetcher).toHaveBeenCalledTimes(1);
    const firstKey = fetcher.mock.calls[0][1].headers["Idempotency-Key"];
    // A fresh observer is what a remounted room creates. No component-local key survives.
    const remounted = new MutationObserver(client, {
      mutationFn: () => apiFetch("/projects/demo/regen-ref?char_id=one", { paidAction: true, method: "POST" }),
    });
    await expect(remounted.mutate()).resolves.toEqual({ job: { id: "accepted" } });
    expect(fetcher.mock.calls[1][1].headers["Idempotency-Key"]).toBe(firstKey);
    fetcher.mockResolvedValueOnce(new Response(JSON.stringify({ job: { id: "new" } })));
    await remounted.mutate();
    expect(fetcher.mock.calls[2][1].headers["Idempotency-Key"]).not.toBe(firstKey);
    client.clear();
  });

  it("keeps indeterminate receipts but separates accounts and changed instructions", async () => {
    const fetcher = vi.fn().mockImplementation(() => Promise.resolve(new Response("indeterminate", { status: 409 })));
    vi.stubGlobal("fetch", fetcher);
    const send = (instruction: string) => apiFetch("/projects/demo/regen-ref-instructed", { paidAction: true, method: "POST", body: JSON.stringify({ instruction }) });
    await expect(send("red coat")).rejects.toThrow();
    await expect(send("red coat")).rejects.toThrow();
    await expect(send("blue coat")).rejects.toThrow();
    auth.id = "account-b";
    await expect(send("red coat")).rejects.toThrow();
    const keys = fetcher.mock.calls.map((call) => call[1].headers["Idempotency-Key"]);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
    expect(keys[3]).not.toBe(keys[0]);
  });

  it("rejects an old account's delayed response even if fetch ignores cancellation", async () => {
    let finish!: (response: Response) => void;
    const fetcher = vi.fn<typeof fetch>(() => new Promise<Response>((resolve) => { finish = resolve; }));
    vi.stubGlobal("fetch", fetcher);
    const request = apiFetch("/credits/balance");
    const rejected = expect(request).rejects.toMatchObject({ name: "AbortError" });
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1));
    clearAccountRequests("account-b");
    finish(new Response(JSON.stringify({ balance_credits: 999 })));
    await rejected;
    expect(fetcher.mock.calls[0][1]?.signal?.aborted).toBe(true);
  });
});

it.each([
  "Compare the current character references before approving Cast. Resume Cast to run its visual review.",
  { code: "cast_approval_rejected", message: "Missing appearance" },
])("releases a definite Cast approval rejection without automatic resubmission: %j", async (detail) => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail }), { status: 409 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: "approved" })));
  vi.stubGlobal("fetch", fetcher);
  const send = () => apiFetch("/projects/demo/approve/cast", { paidAction: true, method: "POST" });
  await expect(send()).rejects.toThrow("API 409");
  expect(fetcher).toHaveBeenCalledTimes(1);
  await expect(send()).resolves.toMatchObject({ status: "approved" });
  expect(fetcher.mock.calls[1][1].headers["Idempotency-Key"])
    .not.toBe(fetcher.mock.calls[0][1].headers["Idempotency-Key"]);
});


it("lets an interrupted provider-free Finish check be explicitly retried without a paid receipt", async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("Connection lost"))
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: "done", preflight: { ready_to_export: true } })));
  vi.stubGlobal("fetch", fetcher);
  const check = () => apiFetch("/projects/demo/export/preflight", { method: "POST" });
  await expect(check()).rejects.toThrow("Connection lost");
  expect(fetcher).toHaveBeenCalledTimes(1);
  await expect(check()).resolves.toMatchObject({ status: "done" });
  for (const call of fetcher.mock.calls) expect(call[1].headers["Idempotency-Key"]).toBeUndefined();
  expect(localStorage.length).toBe(0);
});

it("rechecks cached page evidence without receipts while retaining interrupted paid checks", async () => {
  const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("Connection lost"))
    .mockResolvedValueOnce(new Response(JSON.stringify({ pages: [] })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "idempotency_indeterminate", message: "Interrupted" } }), { status: 409 }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ detail: { code: "idempotency_indeterminate", message: "Interrupted" } }), { status: 409 }));
  vi.stubGlobal("fetch", fetcher);
  const check = (allow_paid: boolean) => apiFetch("/projects/demo/pages/checks/recover", {
    paidAction: allow_paid, method: "POST", body: JSON.stringify({ allow_paid, renders: {} }),
  });
  await expect(check(false)).rejects.toThrow("Connection lost");
  await expect(check(false)).resolves.toEqual({ pages: [] });
  expect(fetcher.mock.calls[0][1].headers["Idempotency-Key"]).toBeUndefined();
  expect(fetcher.mock.calls[1][1].headers["Idempotency-Key"]).toBeUndefined();
  await expect(check(true)).rejects.toMatchObject({ code: "idempotency_indeterminate" });
  await expect(check(true)).rejects.toMatchObject({ code: "idempotency_indeterminate" });
  expect(fetcher.mock.calls[2][1].headers["Idempotency-Key"]).toBeTruthy();
  expect(fetcher.mock.calls[3][1].headers["Idempotency-Key"])
    .toBe(fetcher.mock.calls[2][1].headers["Idempotency-Key"]);
});

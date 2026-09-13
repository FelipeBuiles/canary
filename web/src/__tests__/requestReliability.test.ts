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
  it("releases a replayed Adapt approval rejection for the next explicit attempt", async () => {
    const fetcher = vi.fn()
      .mockRejectedValueOnce(new TypeError("Connection lost"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Adapt requires an approved adaptation brief" }), {
        status: 409, headers: { "Idempotency-Replayed": "true" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "started", stage: "adapt" })));
    vi.stubGlobal("fetch", fetcher);
    const send = () => apiFetch("/projects/demo/run?stage=adapt", { method: "POST" });
    await expect(send()).rejects.toThrow("Connection lost");
    await expect(send()).rejects.toThrow("Adapt requires an approved adaptation brief");
    expect(fetcher).toHaveBeenCalledTimes(2); // No automatic paid retry.
    await expect(send()).resolves.toMatchObject({ status: "started" });
    const keys = fetcher.mock.calls.map((call) => call[1].headers["Idempotency-Key"]);
    expect(keys[1]).toBe(keys[0]);
    expect(keys[2]).not.toBe(keys[0]);
  });

  it("does not retry a lost response; an explicit reattempt after navigation reuses its receipt", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("Connection lost"))
      .mockResolvedValue(new Response(JSON.stringify({ job: { id: "accepted" } }), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const client = createAccountQueryClient(auth.id);
    const firstObserver = new MutationObserver(client, {
      mutationFn: () => apiFetch("/projects/demo/regen-ref?char_id=one", { method: "POST" }),
    });
    await expect(firstObserver.mutate()).rejects.toThrow("Connection lost");
    expect(fetcher).toHaveBeenCalledTimes(1);
    const firstKey = fetcher.mock.calls[0][1].headers["Idempotency-Key"];
    // A fresh observer is what a remounted room creates. No component-local key survives.
    const remounted = new MutationObserver(client, {
      mutationFn: () => apiFetch("/projects/demo/regen-ref?char_id=one", { method: "POST" }),
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
    const send = (instruction: string) => apiFetch("/projects/demo/regen-ref-instructed", { method: "POST", body: JSON.stringify({ instruction }) });
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

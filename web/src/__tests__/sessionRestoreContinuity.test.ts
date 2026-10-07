import { afterEach, describe, expect, it, vi } from "vitest";

// Cache ownership tests reload modules without creating another auth client.
vi.mock("../lib/supabase", () => ({ supabase: { auth: { getSession: vi.fn() } } }));

afterEach(() => {
  vi.resetModules();
  document.cookie = "sw_signed_in=; Path=/; Max-Age=0";
});

describe("session restore continuity", () => {
  it("binds the startup cache to the restored account without replacing it", async () => {
    const module = await import("../api/queryClient");
    const startup = module.queryClient;
    startup.setQueryData(["public-book", "b"], { id: "b" });
    startup.setQueryData(["short-stories"], [{ code: "s" }]);
    startup.setQueryData(["credits", "balance"], 10);

    module.replaceAccountQueryClient("account-a");
    expect(module.queryClient).toBe(startup);
    expect(module.queryClientEpoch).toBe(0);
    expect(startup.getQueryData(["public-book", "b"])).toEqual({ id: "b" });
    expect(startup.getQueryData(["short-stories"])).toEqual([{ code: "s" }]);
    // Anything private from before the account was known is discarded.
    expect(startup.getQueryData(["credits", "balance"])).toBeUndefined();
  });

  it("replaces the cache and remounts on a real account switch", async () => {
    const module = await import("../api/queryClient");
    module.replaceAccountQueryClient("account-a");
    const first = module.queryClient;
    first.setQueryData(["credits", "balance"], 10);
    module.replaceAccountQueryClient("account-b");
    expect(module.queryClient).not.toBe(first);
    expect(module.queryClientEpoch).toBe(1);
    expect(module.queryClient.getQueryData(["credits", "balance"])).toBeUndefined();
  });

  it("keeps account-scoped keys isolated between accounts", async () => {
    const { createAccountQueryClient } = await import("../api/queryClient");
    const a = createAccountQueryClient("a"), b = createAccountQueryClient("b");
    const hash = (client: typeof a, key: unknown[]) => client.getQueryCache().build(client, client.defaultQueryOptions({ queryKey: key })).queryHash;
    expect(hash(a, ["projects"])).not.toBe(hash(b, ["projects"]));
    expect(hash(a, ["public-book", "x"])).toBe(hash(b, ["public-book", "x"]));
  });

  it("sets and clears the presentation-only session hint", async () => {
    const { hasSessionHint, setSessionHint } = await import("../lib/sessionHint");
    setSessionHint(true);
    expect(hasSessionHint()).toBe(true);
    setSessionHint(false);
    expect(hasSessionHint()).toBe(false);
  });
});

import { afterEach, beforeEach, expect, it, vi } from "vitest";

vi.mock("@supabase/supabase-js", () => ({ createClient: vi.fn(() => ({})) }));
beforeEach(() => {
  vi.resetModules();
  vi.stubEnv("VITE_SUPABASE_URL", "https://project.supabase.co");
  vi.stubEnv("VITE_SUPABASE_PUBLISHABLE_KEY", "sb_publishable_test");
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

it("discovers Google using only the public publishable key", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ external: { google: true } }) });
  vi.stubGlobal("fetch", fetch);
  const { getAuthProviders } = await import("../lib/supabase");
  const signal = new AbortController().signal;
  expect(await getAuthProviders(signal)).toEqual({ google: true });
  expect(fetch).toHaveBeenCalledWith("https://project.supabase.co/auth/v1/settings", {
    headers: { apikey: "sb_publishable_test" }, signal,
  });
});

it("does not offer an unconfigured or malformed Google flag", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ external: { google: "true" } }) }));
  const { getAuthProviders } = await import("../lib/supabase");
  expect(await getAuthProviders()).toEqual({ google: false });
});

it("rejects failed provider discovery so the form can keep email available", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false }));
  const { getAuthProviders } = await import("../lib/supabase");
  await expect(getAuthProviders()).rejects.toThrow("Could not load sign-in options");
});

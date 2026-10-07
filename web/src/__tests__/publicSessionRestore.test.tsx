import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode, useSyncExternalStore } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { act, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { setPublicBootstrap, type PublicBootstrap } from "../lib/publicBootstrap";
import { loadPublicPage } from "../lib/publicRoutes";
import { replaceAccountQueryClient } from "../api/queryClient";

const auth = vi.hoisted(() => {
  let state = { session: null as unknown, user: null as unknown, loading: true };
  const listeners = new Set<() => void>();
  return {
    get: () => state,
    set(next: typeof state) { state = next; listeners.forEach((listener) => listener()); },
    subscribe(listener: () => void) { listeners.add(listener); return () => listeners.delete(listener); },
  };
});
vi.mock("../hooks/useAuth", () => ({
  useAuth: () => useSyncExternalStore(auth.subscribe, auth.get, auth.get),
}));

let root: Root | undefined;
afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  setPublicBootstrap({});
  document.body.innerHTML = "";
  vi.unstubAllGlobals();
});

it.skipIf(!existsSync(resolve("dist/public/pricing.html")))(
  "restoring a signed-in session never replaces a hydrated public page",
  async () => {
    const source = new DOMParser().parseFromString(readFileSync(resolve("dist/public/pricing.html"), "utf8"), "text/html");
    setPublicBootstrap(JSON.parse(source.getElementById("public-bootstrap")!.textContent!) as PublicBootstrap);
    document.body.append(document.importNode(source.getElementById("root")!, true));
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
    window.history.replaceState(null, "", "/pricing");
    await loadPublicPage("/pricing");
    const { AccountApp } = await import("../App");
    const heading = screen.getByRole("heading", { level: 1 });
    const recoverable = vi.fn();
    await act(async () => {
      root = hydrateRoot(document.getElementById("root")!, <StrictMode><AccountApp /></StrictMode>, { onRecoverableError: recoverable });
    });
    expect(screen.getByRole("heading", { level: 1 })).toBe(heading);

    // What useAuth does when Supabase restores a stored session.
    await act(async () => {
      replaceAccountQueryClient("account-a");
      auth.set({ session: { user: { id: "account-a" } }, user: { id: "account-a" }, loading: false });
    });
    expect(screen.getByRole("heading", { level: 1 })).toBe(heading);
    expect(screen.queryByText("LOADING…")).toBeNull();
    expect(recoverable).not.toHaveBeenCalled();
  },
);

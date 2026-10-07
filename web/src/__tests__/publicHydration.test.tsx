import { readFileSync, existsSync } from "node:fs";
import { resolve } from "node:path";
import { StrictMode } from "react";
import { hydrateRoot, type Root } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { App } from "../App";
import { loadPublicPage } from "../lib/publicRoutes";
import { setPublicBootstrap, type PublicBootstrap } from "../lib/publicBootstrap";
import { loadCatalog } from "../locales/messages";

vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ session: null, user: null, loading: true }) }));
let root: Root | undefined;
afterEach(async () => {
  await act(async () => root?.unmount());
  root = undefined;
  setPublicBootstrap({});
  document.body.innerHTML = "";
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
// Production markup catches differences hidden by development-only rendering.
for (const [path, file, language, home] of [["/", "home", "en", true], ["/es", "es", "es", true], ["/fr", "fr", "fr", true], ["/pricing", "pricing", "en", false], ["/legal/terms", "legal-terms", "en", false]] as const) {
it.skipIf(!existsSync(resolve(`dist/public/${file}.html`)))(`hydrates ${path} without replacing its content while auth restores`, async () => {
  const documentSource = new DOMParser().parseFromString(readFileSync(resolve(`dist/public/${file}.html`), "utf8"), "text/html");
  const bootstrap = JSON.parse(documentSource.getElementById("public-bootstrap")!.textContent!) as PublicBootstrap;
  setPublicBootstrap(bootstrap);
  const container = documentSource.getElementById("root")!;
  document.body.append(document.importNode(container, true));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  if (bootstrap.stories) client.setQueryData(["short-stories"], bootstrap.stories);
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => [] }));
  const recoverable = vi.fn();
  const errors = vi.spyOn(console, "error").mockImplementation(() => {});
  await loadPublicPage(path);
  await loadCatalog(language);
  window.history.replaceState(null, "", path);
  const heading = screen.getByRole("heading", { level: 1 });
  await act(async () => {
    root = hydrateRoot(document.getElementById("root")!, <StrictMode><QueryClientProvider client={client}><BrowserRouter><App /></BrowserRouter></QueryClientProvider></StrictMode>, { onRecoverableError: recoverable });
  });
  expect(screen.getByRole("heading", { level: 1 })).toBe(heading);
  expect(recoverable).not.toHaveBeenCalled();
  expect(errors).not.toHaveBeenCalled();
  expect(screen.queryByText("OPENING SCENEWRIGHT…")).toBeNull();
  if (home) {
    await act(async () => fireEvent.click(screen.getByRole("button", { name: language === "en" ? "FR" : "EN" })));
    expect(await screen.findByRole("heading", { level: 1, name: language === "en" ? "Votre récit. Sa première scène de BD." : "Your story. Its first comic scene." })).toBeTruthy();
    expect(window.location.pathname).toBe(language === "en" ? "/fr" : "/");
  }
  client.clear();
});
}

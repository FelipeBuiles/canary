import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

const auth = vi.hoisted(() => ({ loading: false, session: null, user: null }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => auth }));

import { AccountApp, App } from "../App";

const values = new Map<string, string>();
const storage: Storage = {
  get length() {
    return values.size;
  },
  clear: () => values.clear(),
  getItem: (key) => values.get(key) ?? null,
  key: (index) => Array.from(values.keys())[index] ?? null,
  removeItem: (key) => values.delete(key),
  setItem: (key, value) => values.set(key, value),
};

describe("public homepage routing", () => {
  beforeEach(() => {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: storage,
    });
    storage.clear();
    auth.loading = false;
    window.history.replaceState(null, "", "/");
  });

  it("shows the homepage at the signed-out root", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter></QueryClientProvider>,
    );

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Your story. Its first comic scene.",
      }),
    ).toBeTruthy();
  });

  it("still sends signed-out visitors on protected routes to sign in", async () => {
    render(
      <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter initialEntries={["/credits"]}>
        <App />
      </MemoryRouter></QueryClientProvider>,
    );

    expect(await screen.findByRole("form", { name: "Sign in" })).toBeTruthy();
  });

  it("renders public pages while authentication is still restoring", async () => {
    auth.loading = true;
    window.history.replaceState(null, "", "/legal/terms");
    render(<AccountApp />);
    expect(await screen.findByRole("heading", { level: 1, name: "Terms of Service" })).toBeTruthy();
  });

  it("keeps protected content gated while authentication is restoring", () => {
    auth.loading = true;
    window.history.replaceState(null, "", "/credits");
    render(<AccountApp />);
    expect(screen.getByText("Loading…")).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
  });
});

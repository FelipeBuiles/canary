import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ loading: false, session: null, user: null }),
}));

import { App } from "../App";

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
  });

  it("shows the homepage at the signed-out root", async () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Turn your novel into a graphic novel you direct.",
      }),
    ).toBeTruthy();
  });

  it("still sends signed-out visitors on protected routes to sign in", async () => {
    render(
      <MemoryRouter initialEntries={["/credits"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("button", { name: "SIGN IN" })).toBeTruthy();
  });
});

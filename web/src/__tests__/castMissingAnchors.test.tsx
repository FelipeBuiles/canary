import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { MissingAnchorsNotice } from "../pages/rooms/CastRoom";
import { missingVisualAnchors } from "../lib/visualAnchor";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({ calls: [] as { path: string; body: unknown }[] }));
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    server.calls.push({ path, body: JSON.parse(String(options?.body ?? "null")) });
    return { story_bible: {}, missing_visual_anchors: [] };
  },
}));

it("lists blank base and appearance-state anchors, never filled ones", () => {
  expect(missingVisualAnchors([
    { id: "ari", name: "Ari", visual_anchor: " ", appearance_states: [{ id: "wet", label: "Soaked", visual_anchor: "" }] },
    { id: "mug", name: "Mug", visual_anchor: "a chipped blue mug" },
  ])).toEqual([
    { key: "ari", entityId: "ari", stateId: null, name: "Ari" },
    { key: "ari:wet", entityId: "ari", stateId: "wet", name: "Ari — Soaked" },
  ]);
});

it("fills one missing description in the series Story Bible from any part", async () => {
  const client = new QueryClient();
  render(
    <QueryClientProvider client={client}>
      <I18nProvider>
        <MissingAnchorsNotice projectId="book~part_0002" missing={[{ key: "mug", entityId: "mug", stateId: null, name: "Mug" }]} />
      </I18nProvider>
    </QueryClientProvider>,
  );

  expect(screen.getByRole("button", { name: "SAVE" }).hasAttribute("disabled")).toBe(true);
  await userEvent.type(screen.getByLabelText("Describe how Mug looks"), "a chipped blue mug");
  await userEvent.click(screen.getByRole("button", { name: "SAVE" }));

  await waitFor(() => expect(server.calls).toEqual([{
    path: "/projects/book/story-bible/visual-anchor",
    body: { entity_id: "mug", appearance_state_id: null, visual_anchor: "a chipped blue mug" },
  }]));
});

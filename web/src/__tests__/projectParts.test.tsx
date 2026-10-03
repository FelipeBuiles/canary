import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { PartSwitcher } from "../components/parts/PartSwitcher";
import {
  invalidateProject, partProjectKey, projectPath, seriesPath, splitProjectKey, withProjectKey,
} from "../api/projectScope";
import type { PartSummary } from "../types/api";
import type * as Client from "../api/client";

const server = vi.hoisted(() => ({ calls: [] as { path: string; method: string; body: unknown }[], grouped: false }));
vi.mock("../api/client", async (original) => ({
  ...await original<typeof Client>(),
  apiFetch: async (path: string, options?: RequestInit) => {
    const method = options?.method ?? "GET";
    const body = options?.body instanceof FormData ? Object.fromEntries(options.body.entries())
      : options?.body ? JSON.parse(String(options.body)) : undefined;
    server.calls.push({ path, method, body });
    if (method === "POST" && path === "/projects/p1/parts") {
      return {
        part: { id: "part_0003", ordinal: 3, title: "Part 3" },
        created: server.grouped ? ["part_0003", "part_0004"] : ["part_0003"],
        chapters: [
          { index: 1, title: "Chapter 9", start_offset: 0, end_offset: 40, characters: 40 },
          { index: 2, title: "Chapter 10", start_offset: 40, end_offset: 90, characters: 50 },
        ],
        parts: [...PARTS, part("part_0003", 3, "Part 3")],
      };
    }
    if (method === "POST" && path.endsWith("/split")) return { parts: PARTS, created: ["part_0004"] };
    throw new Error(`Unexpected fixture API: ${method} ${path}`);
  },
}));

function part(id: string, ordinal: number, title: string, overrides: Partial<PartSummary> = {}): PartSummary {
  return {
    id, ordinal, title, characters: 12000, created_at: "2026-09-01", origin: "paste",
    stages: { extract: "complete", brief: "complete", adapt: "complete", plan: "complete", draw: "running", finish: "pending" },
    page_count: 24, has_cover: false, text_editable: false, text_locked_reason: "This part's adaptation has started, so its text is final.",
    earlier_part_changed: false, ...overrides,
  };
}
const PARTS = [part("part_0001", 1, "The Lighthouse"), part("part_0002", 2, "The Storm", {
  stages: { extract: "pending" }, page_count: 0, text_editable: true, text_locked_reason: null,
})];

afterEach(() => { server.calls = []; server.grouped = false; });

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function renderSwitcher(project = "p1~part_0001") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><I18nProvider>
    <MemoryRouter initialEntries={[`/project/${project}/pages`]}><Routes>
      <Route path="/project/:id/pages" element={<><PartSwitcher project={project} parts={PARTS} /><Where /></>} />
    </Routes></MemoryRouter>
  </I18nProvider></QueryClientProvider>);
}

describe("project keys", () => {
  it("send part work to the part and Look work to the series", () => {
    const key = partProjectKey("p1", "part_0002");
    expect(key).toBe("p1~part_0002");
    expect(splitProjectKey(key)).toEqual({ id: "p1", part: "part_0002" });
    expect(projectPath(key)).toBe("/projects/p1/parts/part_0002");
    expect(seriesPath(key)).toBe("/projects/p1");
    expect(projectPath("p1")).toBe("/projects/p1");
    expect(withProjectKey("/project/p1/pages", key)).toBe("/project/p1~part_0002/pages");
  });

  it("refresh a resource in every part of one project only", async () => {
    const client = new QueryClient();
    const keys = [["project", "p1~part_0001", "status"], ["project", "p1~part_0002", "status"], ["project", "p1", "status"],
      ["project", "p2~part_0001", "status"], ["project", "p1~part_0001", "complete-pages"]];
    for (const key of keys) client.setQueryData(key, 1);
    await invalidateProject(client, "p1~part_0002", "status");
    const refreshed = client.getQueryCache().getAll().filter((query) => query.state.isInvalidated).map((query) => query.queryKey);
    expect(refreshed).toEqual(keys.slice(0, 3));
  });
});

describe("part switcher", () => {
  it("opens another part in the same room", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: "Part" }));
    await user.click(screen.getByRole("option", { name: "2. The Storm" }));
    expect(screen.getByTestId("where").textContent).toBe("/project/p1~part_0002/pages");
  });

  it("adds a part and offers to split it at detected chapters", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: "Part" }));
    await user.click(screen.getByRole("option", { name: "Manage parts…" }));
    const dialog = screen.getByRole("dialog", { name: "Parts" });
    // Only the newest, unadapted part's text can change.
    const first = within(dialog).getByDisplayValue("The Lighthouse").closest("li")!;
    expect(within(first).queryByRole("button", { name: "Replace text" })).toBeNull();
    expect(within(first).getByText("This part's adaptation has started, so its text is final.")).toBeTruthy();
    const second = within(dialog).getByDisplayValue("The Storm").closest("li")!;
    expect(within(second).getByRole("button", { name: "Split" })).toBeTruthy();

    await user.click(within(dialog).getByRole("button", { name: "Add a part" }));
    await user.type(within(dialog).getByLabelText("Or paste the text"), "Chapter 9 The tide turned.");
    await user.click(within(dialog).getByRole("button", { name: "Add part" }));
    await user.click(await within(dialog).findByRole("checkbox", { name: "New part at “Chapter 10”" }));
    await user.click(within(dialog).getByRole("button", { name: "Split into 2 parts" }));

    await waitFor(() => expect(server.calls.at(-1)?.path).toBe("/projects/p1/parts/part_0003/split"));
    expect(server.calls[0]).toMatchObject({ path: "/projects/p1/parts", method: "POST", body: { text: "Chapter 9 The tide turned." } });
    expect(server.calls.at(-1)?.body).toEqual({ boundaries: [40], titles: ["Part 3", "Chapter 10"] });
  });

  it("adds automatically grouped parts without another split action", async () => {
    server.grouped = true;
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: "Part" }));
    await user.click(screen.getByRole("option", { name: "Manage parts…" }));
    const dialog = screen.getByRole("dialog", { name: "Parts" });
    await user.click(within(dialog).getByRole("button", { name: "Add a part" }));
    expect((within(dialog).getByRole("checkbox", { name: "Group long manuscripts into parts at chapter boundaries" }) as HTMLInputElement).checked).toBe(true);
    await user.upload(within(dialog).getByLabelText("Upload a manuscript file"), new File(["Full book"], "book.pdf", { type: "application/pdf" }));
    await user.click(within(dialog).getByRole("button", { name: "Add part" }));

    expect((await within(dialog).findByRole("status")).textContent).toContain("Added 2 parts grouped at chapter boundaries");
    expect(within(dialog).queryByRole("checkbox", { name: "New part at “Chapter 10”" })).toBeNull();
    expect(server.calls).toHaveLength(1);
  });

  it("can keep an appended manuscript together", async () => {
    const user = userEvent.setup();
    renderSwitcher();
    await user.click(screen.getByRole("button", { name: "Part" }));
    await user.click(screen.getByRole("option", { name: "Manage parts…" }));
    const dialog = screen.getByRole("dialog", { name: "Parts" });
    await user.click(within(dialog).getByRole("button", { name: "Add a part" }));
    await user.click(within(dialog).getByRole("checkbox", { name: "Group long manuscripts into parts at chapter boundaries" }));
    await user.type(within(dialog).getByLabelText("Or paste the text"), "Book text");
    await user.click(within(dialog).getByRole("button", { name: "Add part" }));

    await waitFor(() => expect(server.calls).toHaveLength(1));
    expect(server.calls[0].body).toMatchObject({ auto_split: "false" });
  });
});

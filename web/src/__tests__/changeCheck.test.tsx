import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "../i18n";
import { RevisionDraft } from "../components/pages/RevisionDraft";
import { loadRevisionDraft, saveRevisionDraft } from "../api/pageRevisions";

const mocks = vi.hoisted(() => ({ check: vi.fn(), replan: vi.fn(), estimate: vi.fn(), replanEstimate: vi.fn() }));
vi.mock("../api/pages", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/pages")>();
  const cost = { estimate_credits: 1, reserved_credits: 2, reservation_multiplier: 1.2, confidence: "variable" };
  return {
    ...actual,
    getChangeCheckEstimate: (...args: unknown[]) => { mocks.estimate(...args); return Promise.resolve(cost); },
    checkPageChanges: (...args: unknown[]) => { mocks.check(...args); return Promise.resolve({
      page_number: 1, parent_render_revision: 1, changes: [
        { change_id: "tail", route: "draw", instruction: "Panel 2: point the balloon tail at Mrs. White.", reason: "A lettering tail is part of the art." },
        { change_id: "move", route: "plan", instruction: "Move \"The bolt!\" into panel 1.", reason: "Which panel holds a line is set by the page plan." },
      ] }); },
    getPageReplanEstimate: (...args: unknown[]) => { mocks.replanEstimate(...args); return Promise.resolve(cost); },
    replanPage: (...args: unknown[]) => { mocks.replan(...args); return Promise.resolve({ page_number: 1, revision: 3 }); },
  };
});

const target = { comicPageRevision: 2, parentRenderRevision: 1 };

function renderDraft() {
  saveRevisionDraft({ project: "demo", pageNumber: 1, ...target, comicPageSha256: "a".repeat(64),
    changes: [
      { id: "tail", instruction: "the tail should point to the lady", annotations: [] },
      { id: "move", instruction: "this line should be in the first panel", annotations: [] },
    ],
    contextSourceUnitIds: [], updatedAt: new Date().toISOString() });
  render(<QueryClientProvider client={new QueryClient()}><I18nProvider>
    <RevisionDraft project="demo" pageNumber={1} {...target} comicPageSha256={"a".repeat(64)} compareRevision={null}
      issues={[]} onJobQueued={vi.fn()} />
  </I18nProvider></QueryClientProvider>);
}

async function runCheck() {
  fireEvent.click(screen.getByRole("button", { name: "CHECK CHANGES" }));
  const confirm = screen.getAllByRole("button", { name: "CHECK CHANGES" }).at(-1)!;
  await vi.waitFor(() => expect(confirm).toHaveProperty("disabled", false));
  fireEvent.click(confirm);
  await screen.findByText("SUGGESTED WORDING");
}

beforeEach(() => { window.localStorage.clear(); vi.clearAllMocks(); });
afterEach(cleanup);

describe("checking draft changes", () => {
  it("prices the exact draft, then only suggests: the author applies a precise edit", async () => {
    renderDraft();
    await runCheck();
    const body = mocks.check.mock.calls[0]![2];
    expect(body.changes.map((change: { id: string }) => change.id)).toEqual(["tail", "move"]);
    expect(mocks.estimate.mock.calls[0]![2]).toEqual(body);
    // Nothing changed until the author uses the wording.
    expect(screen.getByLabelText("Change 1")).toHaveProperty("value", "the tail should point to the lady");
    fireEvent.click(screen.getByRole("button", { name: "USE THIS WORDING" }));
    expect(screen.getByLabelText("Change 1")).toHaveProperty("value", "Panel 2: point the balloon tail at Mrs. White.");
    expect(screen.getByText("READY TO DRAW")).toBeTruthy();
    expect(loadRevisionDraft("demo", 1, target)?.changes[0]?.instruction).toBe("Panel 2: point the balloon tail at Mrs. White.");
  });

  it("sends a layout change to the page plan instead of the image model", async () => {
    renderDraft();
    await runCheck();
    expect(screen.getByText("BELONGS TO THE PAGE PLAN")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "RE-PLAN THIS PAGE" }));
    const confirm = screen.getAllByRole("button", { name: "RE-PLAN THIS PAGE" }).at(-1)!;
    await vi.waitFor(() => expect(confirm).toHaveProperty("disabled", false));
    expect(mocks.replanEstimate).toHaveBeenCalledWith("demo", 1, true);
    fireEvent.click(confirm);
    await screen.findByText("Page 1 was re-planned. Redraw it so the art matches.");
    expect(mocks.replan).toHaveBeenCalledWith("demo", 1, "Move \"The bolt!\" into panel 1.");
    // The planned change left the image edit; the drawable one stays.
    expect(screen.queryByLabelText("Change 2")).toBeNull();
    expect(screen.getByLabelText("Change 1")).toHaveProperty("value", "the tail should point to the lady");
  });

  it("drops a suggestion once the author rewrites the change", async () => {
    renderDraft();
    await runCheck();
    fireEvent.change(screen.getByLabelText("Change 1"), { target: { value: "make the tail point left" } });
    expect(screen.queryByText("SUGGESTED WORDING")).toBeNull();
  });
});

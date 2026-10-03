import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, useLocation } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { BookStrip } from "../components/parts/BookStrip";
import { partState } from "../lib/partProgress";
import { usePipelineStore } from "../store/pipeline";
import { apiFetch } from "../api/client";
import type * as Client from "../api/client";
import type { PartSummary, StageStatus } from "../types/api";

vi.mock("../api/client", async (original) => ({ ...await original<typeof Client>(), apiFetch: vi.fn() }));
const fetchMock = vi.mocked(apiFetch);
let funding = "api";

function part(ordinal: number, stages: Record<string, StageStatus> = { extract: "pending", brief: "pending" }): PartSummary {
  return {
    id: `part_${String(ordinal).padStart(4, "0")}`, ordinal, title: `Chapters ${ordinal * 6 - 5}–${ordinal * 6}`,
    characters: 90_000 + ordinal * 1000, synopsis: null, created_at: "2026-10-02", origin: "book.pdf", stages,
    page_count: 0, has_cover: false, text_editable: false, text_locked_reason: null, earlier_part_changed: false,
  };
}

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function setup(parts: PartSummary[], project = "p1~part_0001") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(<QueryClientProvider client={client}><I18nProvider>
    <MemoryRouter initialEntries={[`/project/${project}/story`]}>
      <BookStrip project={project} parts={parts} /><Where />
    </MemoryRouter>
  </I18nProvider></QueryClientProvider>);
}

beforeEach(() => {
  localStorage.setItem("canary.uiLanguage", "en");
  funding = "api";
  usePipelineStore.setState({ connect: vi.fn() });
  fetchMock.mockReset();
  fetchMock.mockImplementation(async (path, options) => {
    if (path.includes("/estimate?")) {
      return funding === "api"
        ? { stage: "extract", estimate_credits: 24, reserved_credits: 40, reservation_multiplier: 1.5, confidence: "variable", funding }
        : { stage: "extract", estimate_credits: 0, reserved_credits: 0, reservation_multiplier: 1.25, confidence: "usually_within_estimate", funding };
    }
    if (options?.method === "POST" && path.endsWith("/run?stage=extract")) return { status: "started", stage: "extract" };
    throw new Error(`Unexpected fixture API: ${path}`);
  });
});
afterEach(() => { usePipelineStore.setState(usePipelineStore.getInitialState()); localStorage.clear(); });

describe("book strip", () => {
  it("reads each part's progress from its own stages", () => {
    expect(partState(part(1))).toBe("not_started");
    expect(partState(part(1, { extract: "running", brief: "pending" }))).toBe("analyzing");
    expect(partState(part(1, { extract: "complete", brief: "pending" }))).toBe("needs_brief");
    expect(partState(part(1, { extract: "complete", brief: "awaiting_review" }))).toBe("review");
    expect(partState(part(1, { extract: "complete", brief: "complete" }))).toBe("approved");
    expect(partState(part(1, { extract: "complete", brief: "complete", finish: "complete" }))).toBe("finished");
    expect(partState(part(1, { extract: "complete", brief: "failed" }))).toBe("attention");
  });

  it("keeps every part one click away without loading estimates or starting work", async () => {
    const user = userEvent.setup();
    setup([part(1, { extract: "complete", brief: "awaiting_review" }), part(2), part(3)]);

    expect(screen.getByText("1 of 3 parts analyzed. The rest are saved and wait until you start them.")).toBeTruthy();
    expect(screen.queryByRole("list", { name: "Parts in reading order" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "All 3 parts" }));
    const list = screen.getByRole("list", { name: "Parts in reading order" });
    expect(within(list).getAllByRole("link")).toHaveLength(3);
    expect(within(list).getAllByText("Not started")).toHaveLength(2);
    expect(within(list).getByText("92k characters")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Start Part 2" })).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("offers the next part once this part's brief is approved, then opens its progress", async () => {
    const user = userEvent.setup();
    setup([part(1, { extract: "complete", brief: "complete" }), part(2), part(3)]);

    const start = await screen.findByRole("button", { name: "Start Part 2" });
    expect(await screen.findByLabelText("about 24 credits")).toBeTruthy();
    await waitFor(() => expect((start as HTMLButtonElement).disabled).toBe(false));
    expect(screen.queryByRole("button", { name: "Start Part 3" })).toBeNull();
    await user.click(start);
    const confirmation = screen.getByRole("alertdialog", { name: "Start Part 2" });
    expect(within(confirmation).getByText(/Analyze Part 2 \(Chapters 7–12\)/)).toBeTruthy();
    expect(fetchMock.mock.calls.every(([, options]) => options?.method !== "POST")).toBe(true);
    await user.click(within(confirmation).getByRole("button", { name: "Start Part 2" }));
    await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/project/p1~part_0002/story"));
  });

  it("does not offer a part while another is being analyzed or out of reading order", () => {
    setup([part(1, { extract: "complete", brief: "complete" }), part(2, { extract: "running", brief: "pending" }), part(3)]);
    expect(screen.queryByRole("button", { name: /Start Part/ })).toBeNull();
    expect(screen.getByText(/Part 2 is being analyzed\./)).toBeTruthy();
  });

  it("says subscription-funded work is included rather than quoting zero credits", async () => {
    funding = "codex_subscription";
    setup([part(1, { extract: "complete", brief: "complete" }), part(2)]);
    expect(await screen.findByText("Included in your Codex subscription")).toBeTruthy();
    expect(screen.queryByLabelText("about 0 credits")).toBeNull();
  });
});

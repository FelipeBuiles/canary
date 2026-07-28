import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

vi.mock("../api/queries", () => ({
  useAdaptation: () => ({
    data: {
      treatment: {
        causal_spine: ["A story spine"],
        reveals: ["The hidden truth surfaces"],
      },
      beats: [{
        id: "beat-1",
        order: 1,
        summary: "Thurston finds the evidence",
        narrative_function: "reveal",
        story_functions: ["reveal"],
        source_unit_ids: ["source-1", "source-2"],
        lettering: [{ id: "letter-1" }],
        transitions: [{ description: "Knowledge changes" }],
        appearance_changes: [],
      }],
      ledger: [
        { source_unit_id: "source-1", disposition: "depicted", adapted_beat_ids: ["beat-1"] },
        { source_unit_id: "source-2", disposition: "compressed_into", adapted_beat_ids: ["beat-1"], reason: "Combined for pace" },
      ],
    },
    isLoading: false,
    error: null,
  }),
  useBookPlan: () => ({
    data: {
      rhythm_summary: "A steady rhythm",
      target_page_min: 1,
      target_page_max: 3,
      pages: [{ page_number: 1, revision: 1, content_sha256: "a".repeat(64) }],
    },
    isLoading: false,
    error: null,
  }),
  useCompletePages: () => ({
    data: {
      pages: [{
        page: {
          page_number: 1,
          revision: 1,
          content_sha256: "a".repeat(64),
          page_turn_role: "reveal",
          spread_role: "single",
          emphasis: "peak",
          density_intent: "standard",
          rhythm_intent: "Hold, then reveal",
          layout_intent: "One dominant reveal",
          content: [{ beat_ids: ["beat-1"], lettering: [{ id: "letter-1" }] }],
          reading_order: [],
        },
        active_render: null,
        issues: [],
      }],
      issue_summary: { unresolved_issue_ids: [], blocking_issue_ids: [], accepted_editorial_issue_ids: [] },
    },
    isLoading: false,
    error: null,
  }),
}));

import { InspectDrawer } from "../components/InspectDrawer";

describe("InspectDrawer", () => {
  it.each([
    ["adaptation", "BOOK ADAPTATION"],
    ["page-plan", "PAGE PLAN"],
  ] as const)("renders the %s drawer above shell layers", (kind, title) => {
    render(
      <I18nProvider>
        <InspectDrawer project="demo" kind={kind} onClose={() => undefined} />
      </I18nProvider>,
    );

    const drawer = screen.getByRole("dialog", { name: title });
    expect(drawer.className).toContain("z-[120]");
    expect(drawer.querySelector("header")?.className).toContain("md:h-shell-top");
    expect(drawer.querySelector("header")?.className).toContain("sticky");
  });

  it("closes through its visible header control", () => {
    const onClose = vi.fn();
    render(
      <I18nProvider>
        <InspectDrawer project="demo" kind="adaptation" onClose={onClose} />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("button", { name: "CLOSE" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("closes from the backdrop without closing when its content is clicked", () => {
    const onClose = vi.fn();
    render(
      <I18nProvider>
        <InspectDrawer project="demo" kind="adaptation" onClose={onClose} />
      </I18nProvider>,
    );

    fireEvent.click(screen.getByRole("heading", { name: "NARRATIVE TREATMENT" }));
    expect(onClose).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("dialog", { name: "BOOK ADAPTATION" }));
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("shows page-level plan detail instead of only a page count", () => {
    render(
      <I18nProvider>
        <InspectDrawer project="demo" kind="page-plan" onClose={() => undefined} />
      </I18nProvider>,
    );

    expect(screen.getByText("PAGE REGISTER")).toBeTruthy();
    expect(screen.getByText("Target range 1–3")).toBeTruthy();
    expect(screen.getByText("One dominant reveal")).toBeTruthy();
    expect(screen.getByText("Hold, then reveal")).toBeTruthy();
  });

  it("shows adaptation accounting and beat detail instead of only a count", () => {
    render(
      <I18nProvider>
        <InspectDrawer project="demo" kind="adaptation" onClose={() => undefined} />
      </I18nProvider>,
    );

    expect(screen.getByText("SOURCE ACCOUNTING")).toBeTruthy();
    expect(screen.getByText(/hidden truth surfaces/)).toBeTruthy();
    expect(screen.getByText("Thurston finds the evidence")).toBeTruthy();
    expect(screen.getByText(/1 transitions/)).toBeTruthy();
  });
});

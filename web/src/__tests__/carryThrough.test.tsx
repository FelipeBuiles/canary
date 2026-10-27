import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CarryThrough } from "../components/pages/CarryThrough";
import type { NoteChange, NoteClaim } from "../api/notes";
import { I18nProvider } from "../i18n";

const api = vi.hoisted(() => ({
  previewNote: vi.fn(),
  getNoteChecksEstimate: vi.fn(),
  checkNotePages: vi.fn(),
  getNoteApplyEstimate: vi.fn(),
  applyNote: vi.fn(),
  undoNote: vi.fn(),
}));
vi.mock("../api/notes", () => api);

const look: NoteClaim = {
  kind: "look", entity_id: "mrs_white", fact: "She took her apron off.", start_page: 17, end_page: null,
  state_id: null, look_label: "Without apron", look_anchor: "dress, shawl, no apron",
};

function change(overrides: Partial<NoteChange> = {}): NoteChange {
  return {
    id: "note_aaaaaaaaaaaa", page_number: 17, note: "No apron.", claim: look, status: "proposed",
    scope: {
      pages: [17, 18, 19, 20].map((page_number) => ({ page_number, panels: [1], drawn: true, reason: "look" as const })),
      beat_ids: ["beat_1"], end_page: 20, from_state_id: null,
    },
    checks: [], pages: [], state_id: null, added_state: false, redraw_pages: [],
    check_pages: [18, 19, 20], default_pages: [17, 18, 19, 20],
    ...overrides,
  };
}

const estimate = { estimate_credits: 3, reserved_credits: 4, reservation_multiplier: 1.2, confidence: "high", pages: [] };

function view(claim: NoteClaim = look) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <I18nProvider><CarryThrough project="owner:p" pageNumber={17} note="No apron." claim={claim} /></I18nProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getNoteChecksEstimate.mockResolvedValue(estimate);
  api.getNoteApplyEstimate.mockResolvedValue(estimate);
});

describe("CarryThrough", () => {
  it("lists the pages, checks the drawn ones, and changes only those that break the fact", async () => {
    const user = userEvent.setup();
    api.previewNote.mockResolvedValue(change());
    api.checkNotePages.mockResolvedValue(change({
      checks: [18, 19, 20].map((page_number) => ({ page_number, render_revision: 1, breaks_fact: page_number === 19,
        panels: page_number === 19 ? [2] : [], evidence: "" })),
      default_pages: [17, 19],
    }));
    api.applyNote.mockResolvedValue(change({ status: "applied", pages: [17, 19], redraw_pages: [17, 19],
      added_state: true, state_id: "without_apron" }));
    view();

    expect(screen.getByText("THIS GOES BEYOND PAGE 17")).toBeTruthy();
    expect(api.previewNote).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "SHOW THE PAGES IT TOUCHES" }));
    expect(await screen.findByText("Shows on 4 pages: 17, 18, 19, 20.")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "CHECK 3 DRAWN PAGES" }));
    const confirmCheck = await screen.findAllByRole("button", { name: "CHECK PAGES" });
    await waitFor(() => expect((confirmCheck.at(-1) as HTMLButtonElement).disabled).toBe(false));
    await user.click(confirmCheck.at(-1)!);
    expect(await screen.findByText("The art breaks it on 19.")).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "APPLY" }));
    const chips = await screen.findAllByRole("checkbox");
    expect(chips.map((chip) => (chip as HTMLInputElement).checked)).toEqual([true, false, true, false]);
    const confirm = screen.getAllByRole("button", { name: "APPLY" }).at(-1) as HTMLButtonElement;
    await waitFor(() => expect(confirm.disabled).toBe(false));
    await user.click(confirm);
    await waitFor(() => expect(api.applyNote).toHaveBeenCalledWith("owner:p", "note_aaaaaaaaaaaa", [17, 19]));
    expect(await screen.findByText("CARRIED THROUGH")).toBeTruthy();
    expect(screen.getByText("Draw the new look in Look before redrawing those pages.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "UNDO" })).toBeTruthy();
  });

  it("offers a script change where a redraw can't help, and undoes it", async () => {
    const user = userEvent.setup();
    const line: NoteClaim = { kind: "line", lettering_item_id: "l1", text: "He paused to strike another.",
      speaker_entity_id: null };
    const scoped = change({ claim: line, check_pages: [], default_pages: [17],
      scope: { pages: [{ page_number: 17, panels: [2], drawn: true, reason: "line" }], beat_ids: ["b"], end_page: null,
        from_state_id: null } });
    api.previewNote.mockResolvedValue(scoped);
    api.applyNote.mockResolvedValue({ ...scoped, status: "applied", pages: [17], redraw_pages: [17] });
    api.undoNote.mockResolvedValue({ ...scoped, status: "undone" });
    view(line);

    expect(screen.getByText("THIS CHANGES THE SCRIPT")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "SHOW THE PAGES IT TOUCHES" }));
    expect(await screen.findByText("Touches page 17.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /DRAWN PAGES/ })).toBeNull();
    await user.click(screen.getByRole("button", { name: "APPLY" }));
    expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
    const confirm = screen.getAllByRole("button", { name: "APPLY" }).at(-1) as HTMLButtonElement;
    await waitFor(() => expect(confirm.disabled).toBe(false));
    await user.click(confirm);
    await user.click(await screen.findByRole("button", { name: "UNDO" }));
    expect(await screen.findByText("Undone. The script and pages are as they were.")).toBeTruthy();
  });
});

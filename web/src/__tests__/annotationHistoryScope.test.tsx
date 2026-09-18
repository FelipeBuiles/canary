import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { I18nProvider } from "../i18n";
import { RevisionDraft } from "../components/pages/RevisionDraft";
import type { PageIssue } from "../types/api";

vi.mock("../api/queries", () => ({
  useAdaptation: () => ({ data: { beats: [] }, isLoading: false, error: null }),
}));

vi.mock("../api/pageRevisions", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/pageRevisions")>();
  return {
    ...actual,
    useCorrectionPreview: () => ({ mutate: vi.fn(), isPending: false, data: undefined, error: null }),
    useSubmitCorrections: () => ({ mutate: vi.fn(), isPending: false, error: null }),
    useRenderCorrection: () => ({ data: null, isLoading: false, error: null }),
  };
});

const FACE_ISSUE: PageIssue = {
  id: "issue-9",
  issue_type: "identity",
  classification: "editorial_issue",
  correction_kind: "render_fidelity",
  correction_owner: "draw",
  page_number: 1,
  render_revision: 1,
  evidence: ["Face differs from approved reference"],
  requested_correction: "Restore the approved face",
  status: "open",
  resolution_revision: null,
};

const TOWER_ISSUE: PageIssue = {
  id: "issue-7",
  issue_type: "identity",
  classification: "editorial_issue",
  correction_kind: "render_fidelity",
  correction_owner: "draw",
  page_number: 1,
  render_revision: 1,
  evidence: ["Tower leans against the approved reference"],
  requested_correction: "Straighten the leaning tower",
  status: "open",
  resolution_revision: null,
};

function markFields(container: HTMLElement): HTMLInputElement[] {
  return [...container.querySelectorAll('[id^="mark-note-"]')] as HTMLInputElement[];
}

describe("RevisionDraft focused-fix history scope", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("cannot undo one fix's marks into another fix", () => {
    const { container } = render(
      <QueryClientProvider client={new QueryClient()}>
        <I18nProvider>
          <RevisionDraft
            project="demo"
            pageNumber={1}
            comicPageRevision={2}
            parentRenderRevision={1}
            comicPageSha256={"a".repeat(64)}
            compareRevision={null}
            issues={[FACE_ISSUE, TOWER_ISSUE]}
            seeds={[]}
            onSeedsConsumed={vi.fn()}
            onDraftKeysChange={vi.fn()}
            onJobQueued={vi.fn()}
          />
        </I18nProvider>
      </QueryClientProvider>,
    );

    // The default view is artwork only; editing and marking are explicit.
    expect(screen.queryByRole("button", { name: /mark on page/i })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /make changes/i }));

    // Production starts with the first selected fix expanded; the rest collapsed.
    expect(screen.getByDisplayValue("Restore the approved face")).toBeTruthy();
    const editButtons = () => screen.getAllByRole("button", { name: /edit request/i });
    expect(editButtons()).toHaveLength(1);

    // Mark the focused fix through the real annotator UI.
    fireEvent.click(screen.getByRole("button", { name: /mark on page/i }));
    expect(screen.getByRole("button", { name: /done marking/i }).getAttribute("aria-pressed")).toBe("true");
    fireEvent.click(screen.getByText("More"));
    fireEvent.click(screen.getByRole("button", { name: /without drawing/i }));
    expect(markFields(container)).toHaveLength(1);
    fireEvent.change(markFields(container)[0]!, { target: { value: "alpha mark on the face" } });
    expect(markFields(container)[0]?.value).toBe("alpha mark on the face");

    // Switch focus to the second fix: its canvas starts clean.
    fireEvent.click(editButtons()[0]!);
    expect(screen.getByDisplayValue("Straighten the leaning tower")).toBeTruthy();
    expect(markFields(container)).toHaveLength(0);
    expect(screen.queryByDisplayValue("alpha mark on the face")).toBeNull();

    // Undo after the switch cannot pull the other fix's marks in.
    fireEvent.click(screen.getByText("More"));
    expect((screen.getByRole("button", { name: /undo/i }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: /undo/i }));
    expect(markFields(container)).toHaveLength(0);

    // The first fix still owns its mark, untouched.
    fireEvent.click(screen.getByRole("button", { name: /edit request/i }));
    expect(markFields(container)).toHaveLength(1);
    expect(markFields(container)[0]?.value).toBe("alpha mark on the face");
  });
});

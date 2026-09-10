import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import type { ShortStory } from "../types/api";

const catalogResult = {
  data: [] as ShortStory[],
  isLoading: false,
  isError: false,
  isFetching: false,
  refetch: vi.fn(),
};

vi.mock("../api/queries", () => ({
  useShortStories: () => catalogResult,
}));

import { UploadStep } from "../components/wizard/UploadStep";

describe("UploadStep keyboard flow", () => {
  beforeEach(() => {
    catalogResult.data = [];
    catalogResult.isLoading = false;
    catalogResult.isError = false;
    catalogResult.refetch.mockReset();
  });
  it("uses Enter to advance first, then submit the named project", async () => {
    const user = userEvent.setup();
    const onSubmitImport = vi.fn();

    render(
      <I18nProvider>
        <UploadStep
          onSubmit={() => undefined}
          onSubmitImport={onSubmitImport}
          isPending={false}
          error={null}
        />
      </I18nProvider>,
    );

    await user.click(screen.getByText("USE ANOTHER SOURCE"));
    const source = screen.getByPlaceholderText("e.g. story URL or library code");
    await user.type(source, "the-last-incantation{Enter}");

    expect((screen.getByLabelText("PROJECT NAME") as HTMLInputElement).value).toBe("The Last Incantation");
    expect(onSubmitImport).not.toHaveBeenCalled();

    const projectName = screen.getByLabelText("PROJECT NAME");
    await user.click(projectName);
    await user.keyboard("{Enter}");

    expect(onSubmitImport).toHaveBeenCalledTimes(1);
    expect(onSubmitImport).toHaveBeenCalledWith(
      "the-last-incantation",
      "The Last Incantation",
      expect.objectContaining({ target_language: "en" }),
    );
  });

  it("bounds catalog choices and keeps the selected source across search and details", async () => {
    const user = userEvent.setup();
    catalogResult.data = Array.from({ length: 1077 }, (_, index) => ({
      code: `story-${index}`, title: `Story ${String(index).padStart(4, "0")}`, author: "Catalog author", words: 2000, genres: ["literary"],
    }));
    catalogResult.data.push(
      { code: "the-gift-of-the-magi", title: "The Gift of the Magi", author: "O. Henry", words: 2057, genres: ["literary"] },
      { code: "the-open-window", title: "The Open Window", author: "Saki", words: 1274, genres: ["quirky"] },
      { code: "the-most-dangerous-game", title: "The Most Dangerous Game", author: "Richard Connell", words: 7949, genres: ["adventure"] },
    );
    const submit = vi.fn();
    render(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={submit} isPending={false} error={null} /></I18nProvider>);
    const choices = screen.getByLabelText("SHORT STORY LIBRARY");
    expect(within(choices).getAllByRole("button")).toHaveLength(3);
    await user.click(within(choices).getByRole("button", { name: /The Open Window/ }));
    await user.click(screen.getByRole("button", { name: "BROWSE ALL STORIES" }));
    expect(within(choices).getAllByRole("button")).toHaveLength(8);
    await user.click(screen.getByRole("button", { name: "NEXT" }));
    expect(within(choices).queryByRole("button", { name: /Story 0000/ })).toBeNull();
    await user.type(screen.getByRole("searchbox"), "Story 0000");
    expect(within(choices).getAllByRole("button")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "CONTINUE" }));
    expect((screen.getByLabelText("PROJECT NAME") as HTMLInputElement).value).toBe("The Open Window");
    await user.click(screen.getByRole("button", { name: "CREATE PROJECT" }));
    expect(submit).toHaveBeenCalledWith("the-open-window", "The Open Window", { target_language: "en" });
  });

  it("distinguishes loading, catalog failure, and an empty catalog while upload remains available", async () => {
    const user = userEvent.setup();
    const content = <I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>;
    catalogResult.isLoading = true;
    const view = render(content);
    expect(screen.getByRole("status").textContent).toContain("LOADING SAMPLE STORIES");
    catalogResult.isLoading = false;
    catalogResult.isError = true;
    view.rerender(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    expect(screen.getByRole("alert").textContent).toContain("THE SAMPLE LIBRARY COULD NOT LOAD");
    await user.click(screen.getByRole("button", { name: "TRY AGAIN" }));
    expect(catalogResult.refetch).toHaveBeenCalledOnce();
    catalogResult.isError = false;
    view.rerender(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    expect(screen.getByRole("status").textContent).toContain("The sample library is empty.");
    await user.click(screen.getByRole("button", { name: "UPLOAD MANUSCRIPT" }));
    expect((screen.getByRole("button", { name: "DROP FILE OR CLICK TO BROWSE" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("does not estimate PDF prose from file size and submits the current output settings", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    const { container } = render(<I18nProvider><UploadStep onSubmit={submit} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    await user.click(screen.getByRole("button", { name: "UPLOAD MANUSCRIPT" }));
    const file = new File(["compressed document bytes"], "My manuscript.pdf", { type: "application/pdf" });
    await user.upload(container.querySelector<HTMLInputElement>('input[type="file"]')!, file);
    await user.click(screen.getByRole("button", { name: "CONTINUE" }));
    expect(screen.queryByText("Rough whole-book estimate")).toBeNull();
    expect(screen.queryByRole("button", { name: "GENERATION QUALITY" })).toBeNull();
    expect(screen.getByText(/Review a live credit estimate/)).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "CREATE PROJECT" }));
    expect(submit).toHaveBeenCalledWith(file, "My manuscript", { target_language: "en" });
  });
});

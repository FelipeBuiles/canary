import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import type { ShortStory, SourcePreview } from "../types/api";
import { ApiError } from "../api/client";

const readStory = vi.hoisted(() => vi.fn());
vi.mock("../api/projects", () => ({ readShortStory: readStory }));

const catalogResult = {
  data: [] as ShortStory[],
  isLoading: false,
  isError: false,
  isFetching: false,
  refetch: vi.fn(),
};

type PreviewResult = { isPending: boolean; isError: boolean; error: unknown; data?: SourcePreview };
const previewResult: PreviewResult = { isPending: true, isError: false, error: null };
const previewedFiles: (File | null)[] = [];

vi.mock("../api/queries", () => ({
  useShortStories: () => catalogResult,
  useSourcePreview: (file: File | null) => { previewedFiles.push(file); return previewResult; },
}));

import { UploadStep } from "../components/wizard/UploadStep";

describe("UploadStep keyboard flow", () => {
  beforeEach(() => {
    readStory.mockReset();
    catalogResult.data = [];
    catalogResult.isLoading = false;
    catalogResult.isError = false;
    catalogResult.refetch.mockReset();
    Object.assign(previewResult, { isPending: true, isError: false, error: null, data: undefined });
    previewedFiles.length = 0;
    localStorage.clear();
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

    await user.click(screen.getByText("Have a story code or link?"));
    const source = screen.getByPlaceholderText("e.g. the-open-window");
    await user.type(source, "the-last-incantation{Enter}");

    expect((screen.getByLabelText("Production name") as HTMLInputElement).value).toBe("The Last Incantation");
    expect(onSubmitImport).not.toHaveBeenCalled();

    const projectName = screen.getByLabelText("Production name");
    await user.click(projectName);
    await user.keyboard("{Enter}");

    expect(onSubmitImport).not.toHaveBeenCalled();
    expect((screen.getByRole("button", { name: "Create project" }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByRole("radio", { name: /Integrated lettering/ }));
    await user.keyboard("{Enter}");

    expect(onSubmitImport).toHaveBeenCalledTimes(1);
    expect(onSubmitImport).toHaveBeenCalledWith(
      "the-last-incantation",
      "The Last Incantation",
      expect.objectContaining({ target_language: "en", lettering_mode: "integrated" }),
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
    await user.click(screen.getByRole("button", { name: "All 1,080 samples and 0 classics" }));
    let choices = screen.getByLabelText("Story choices");
    expect(within(choices).getAllByRole("article")).toHaveLength(8);
    await user.type(screen.getByRole("searchbox", { name: "Search stories" }), "The Open Window");
    choices = screen.getByLabelText("Story choices");
    await user.click(within(choices).getByRole("button", { name: "CHOOSE STORY" }));
    await user.clear(screen.getByRole("searchbox", { name: "Search stories" }));
    await user.click(screen.getByRole("button", { name: "NEXT" }));
    expect(screen.queryByText("Story 0000")).toBeNull();
    await user.type(screen.getByRole("searchbox", { name: "Search stories" }), "Story 0000");
    expect(within(screen.getByLabelText("Story choices")).getAllByRole("article")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect((screen.getByLabelText("Production name") as HTMLInputElement).value).toBe("The Open Window");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "Create project" }));
    expect(submit).toHaveBeenCalledWith("the-open-window", "The Open Window", { target_language: "en", lettering_mode: "editable" });
  });

  it("opens the complete source and starts from the story the reader chose", async () => {
    const user = userEvent.setup();
    catalogResult.data = [{
      code: "kaitlin-out-of-space", title: "Kaitlin Out of Space", author: "Krishan Coupland",
      words: 3000, genres: ["sci-fi"], description: "A visitor from the stars.",
    }];
    readStory.mockResolvedValue({ code: "kaitlin-out-of-space", text: "KAITLIN OUT OF SPACE\nBy Krishan Coupland\n\nFirst paragraph.\n\nSecond paragraph." });
    render(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);

    await user.click(screen.getByRole("button", { name: "All 1 samples and 0 classics" }));
    await user.click(screen.getByRole("button", { name: "READ STORY" }));
    expect(await screen.findByText("First paragraph.")).toBeTruthy();
    expect(screen.getByText("Second paragraph.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: /USE THIS STORY/ }));
    expect((screen.getByLabelText("Production name") as HTMLInputElement).value).toBe("Kaitlin Out of Space");
    expect(readStory).toHaveBeenCalledWith("kaitlin-out-of-space", expect.any(AbortSignal));
  });

  it("keeps a story requested before signup selected when the catalog loads", async () => {
    const user = userEvent.setup();
    catalogResult.data = [{ code: "an-education", title: "An Education", author: "Angie", words: 955, genres: ["fantasy"] }];
    render(<I18nProvider><UploadStep initialStoryCode="an-education" onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    expect((screen.getByRole("radio", { name: /An Education/ }) as HTMLInputElement).checked).toBe(true);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect((screen.getByLabelText("Production name") as HTMLInputElement).value).toBe("An Education");
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
    expect((screen.getByRole("button", { name: "Drop your manuscript or browse your files" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("does not estimate PDF prose from file size and submits the current output settings", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    const { container } = render(<I18nProvider><UploadStep onSubmit={submit} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    const file = new File(["compressed document bytes"], "My manuscript.pdf", { type: "application/pdf" });
    await user.upload(container.querySelector<HTMLInputElement>('input[type="file"]')!, file);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.queryByText("Rough whole-book estimate")).toBeNull();
    expect(screen.queryByRole("button", { name: "GENERATION QUALITY" })).toBeNull();
    expect(screen.getByRole("heading", { name: "What happens next" })).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "Create project" }));
    expect(submit).toHaveBeenCalledWith(file, "My manuscript", { target_language: "en", lettering_mode: "editable" });
  });

  it("creates a project from pasted text, titled by its first line", async () => {
    const user = userEvent.setup();
    const submit = vi.fn();
    render(<I18nProvider><UploadStep onSubmit={submit} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(true);
    await user.click(screen.getByLabelText("Paste your text"));
    await user.paste("The Lighthouse\n\nThe keeper climbed the stairs at dusk.");
    expect(screen.getByText("9 words")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect((screen.getByLabelText("Production name") as HTMLInputElement).value).toBe("The Lighthouse");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    await user.click(screen.getByRole("radio", { name: /Editable lettering/ }));
    await user.click(screen.getByRole("button", { name: "Create project" }));
    const [file, name] = submit.mock.calls[0];
    expect(name).toBe("The Lighthouse");
    expect(file.name).toBe("pasted-manuscript.txt");
    expect(file.type).toBe("text/plain");
    expect(await file.text()).toBe("The Lighthouse\n\nThe keeper climbed the stairs at dusk.");
  });

  it("accepts text pasted onto the drop zone and lets text replace a chosen file", async () => {
    const user = userEvent.setup();
    const { container } = render(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    await user.upload(container.querySelector<HTMLInputElement>('input[type="file"]')!, new File(["x"], "draft.txt", { type: "text/plain" }));
    expect(screen.getByRole("button", { name: "Replace file draft.txt" })).toBeTruthy();
    fireEvent.paste(screen.getByRole("button", { name: "Replace file draft.txt" }), { clipboardData: { files: [], getData: () => "Copied from a doc" } });
    expect(screen.queryByRole("button", { name: "Replace file draft.txt" })).toBeNull();
    expect((screen.getByLabelText("Paste your text") as HTMLTextAreaElement).value).toBe("Copied from a doc");
  });

  it("points users of other apps to pasting when the file type is unsupported", async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { container } = render(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    await user.upload(container.querySelector<HTMLInputElement>('input[type="file"]')!, new File(["x"], "novel.rtf"));
    expect(screen.getByRole("alert").textContent).toContain("copy the text and paste it below");
    expect(screen.getByRole("alert").textContent).toContain(".docx");
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("previews the parts creation will make before the project exists", async () => {
    const user = userEvent.setup();
    Object.assign(previewResult, { isPending: false, data: {
      characters: 420_000, words: 75_000, chapters: 24, part_target_characters: 100_000,
      parts: [
        { title: "Chapters 1–6", characters: 100_000, words: 18_000 },
        { title: "Chapters 7–12", characters: 100_000, words: 19_000 },
        { title: "Chapters 13–18", characters: 100_000, words: 19_000 },
        { title: "Chapters 19–24", characters: 120_000, words: 19_000 },
      ],
    } });
    const { container } = render(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    const file = new File(["x"], "novel.docx");
    await user.upload(container.querySelector<HTMLInputElement>('input[type="file"]')!, file);
    expect(previewedFiles.every((previewed) => previewed === null)).toBe(true);
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(previewedFiles.at(-1)).toBe(file);
    expect(screen.getByText(/75,000 words/)).toBeTruthy();
    expect(screen.getByText(/24 chapters found/)).toBeTruthy();
    expect(screen.getByText(/Splits into 4 parts/)).toBeTruthy();
    expect(screen.getByText("Chapters 19–24")).toBeTruthy();
    expect(screen.queryByText(/very short/)).toBeNull();
  });

  it("warns about short or unsplittable text without blocking it", async () => {
    const user = userEvent.setup();
    Object.assign(previewResult, { isPending: false, data: {
      characters: 900, words: 160, chapters: 1, part_target_characters: 100_000,
      parts: [{ title: null, characters: 900, words: 160 }],
    } });
    render(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    await user.click(screen.getByLabelText("Paste your text"));
    await user.paste("A short scene.");
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(previewedFiles.at(-1)?.name).toBe("pasted-manuscript.txt");
    expect(screen.getByText(/This is very short/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(false);

    Object.assign(previewResult, { data: { characters: 300_000, words: 54_000, chapters: 1, part_target_characters: 100_000,
      parts: [{ title: null, characters: 300_000, words: 54_000 }] } });
    await user.click(screen.getByRole("button", { name: "Back" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText(/No chapter headings were found/)).toBeTruthy();
  });

  it("stops at step 2 when the server cannot read the manuscript", async () => {
    const user = userEvent.setup();
    Object.assign(previewResult, { isPending: false, isError: true, error: new ApiError(400, "Encrypted PDFs are not supported.") });
    const { container } = render(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    await user.upload(container.querySelector<HTMLInputElement>('input[type="file"]')!, new File(["x"], "locked.pdf"));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByRole("alert").textContent).toBe("Encrypted PDFs are not supported.");
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(true);

    Object.assign(previewResult, { error: new ApiError(503, "Service unavailable") });
    await user.click(screen.getByRole("button", { name: "Back" }));
    await user.click(screen.getByRole("button", { name: "Continue" }));
    expect(screen.getByText(/You can still create the project/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Continue" }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("keeps pasted text as a local draft and restores it on the manuscript tab", async () => {
    const user = userEvent.setup();
    const first = render(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    await user.click(screen.getByLabelText("Paste your text"));
    await user.paste("Draft prose that must survive.");
    await vi.waitFor(() => expect(localStorage.getItem("canary.manuscriptDraft")).toBe("Draft prose that must survive."));
    first.unmount();

    render(<I18nProvider><UploadStep onSubmit={vi.fn()} onSubmitImport={vi.fn()} isPending={false} error={null} /></I18nProvider>);
    expect((screen.getByLabelText("Paste your text") as HTMLTextAreaElement).value).toBe("Draft prose that must survive.");
    expect(screen.getByText("Restored the text you pasted last time.")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Clear" }));
    expect((screen.getByLabelText("Paste your text") as HTMLTextAreaElement).value).toBe("");
    await vi.waitFor(() => expect(localStorage.getItem("canary.manuscriptDraft")).toBeNull());
  });
});

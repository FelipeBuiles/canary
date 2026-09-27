import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { PageVersions } from "../components/pages/PageVersions";

const api = vi.hoisted(() => ({ detail: vi.fn(), select: vi.fn() }));
vi.mock("../api/queries", () => ({ useCompletePage: api.detail }));
vi.mock("../api/pages", () => ({ selectPageRender: api.select,
  pageRenderPreviewUrl: (_project: string, _page: number, revision: number) => `/art/${revision}` }));
beforeEach(() => {
  vi.resetAllMocks();
  api.detail.mockReturnValue({ data: { page: { revision: 1, content_sha256: "page" }, renders: [1, 2, 3, 4].map(revision => ({
    render: { revision, comic_page_revision: 1, comic_page_sha256: "page" },
  })) } });
  api.select.mockResolvedValue({ active_render_revision: 3 });
});
function setup(disabled = false) {
  const selected = vi.fn();
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  render(<QueryClientProvider client={client}><I18nProvider><PageVersions project="demo" pageNumber={6}
    activeRevision={4} disabled={disabled} onSelected={selected} /></I18nProvider></QueryClientProvider>);
  return { selected, invalidate };
}
it("previews without mutation, then selects with the expected active revision and refreshes consumers", async () => {
  const { selected, invalidate } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Revision 3" }));
  expect(screen.getByRole("img", { name: "Page 6, Revision 3" }).getAttribute("src")).toBe("/art/3");
  expect(api.select).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Use this version" }));
  await waitFor(() => expect(selected).toHaveBeenCalledOnce());
  expect(api.select).toHaveBeenCalledWith("demo", 6, 3, 4);
  expect(invalidate).toHaveBeenCalledWith({ queryKey: ["project", "demo"] });
});
it("allows inspection but prevents selection while drawing", () => {
  setup(true);
  fireEvent.click(screen.getByRole("button", { name: "Revision 3" }));
  expect((screen.getByRole("button", { name: "Use this version" }) as HTMLButtonElement).disabled).toBe(true);
});
it("shows a conflict without leaving version history", async () => {
  api.select.mockRejectedValue(new Error("The selected version changed. Refresh and choose again."));
  const { selected } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Revision 3" }));
  fireEvent.click(screen.getByRole("button", { name: "Use this version" }));
  expect((await screen.findByRole("alert")).textContent).toContain("The selected version changed.");
  expect(selected).not.toHaveBeenCalled();
});

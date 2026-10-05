import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const estimate = vi.fn();
const redraw = vi.fn();
vi.mock("../api/pages", () => ({
  getPageRedrawEstimate: (...args: unknown[]) => estimate(...args),
  redrawOutOfDatePages: (...args: unknown[]) => redraw(...args),
}));
import { OutOfDatePages } from "../components/pages/OutOfDatePages";

import type { PageRedrawChange } from "../types/api";

const carl: PageRedrawChange = { reference_id: "carl", entity_id: "carl", appearance_state_id: null, label: "Carl", reasons: ["image"] };
const key: PageRedrawChange = { reference_id: "key", entity_id: "key", appearance_state_id: null, label: "Key", reasons: ["description"] };
const redraws = [
  { page_number: 3, plan_changed: false, changed_references: [carl, key] },
  { page_number: 7, plan_changed: true, changed_references: [carl] },
];

beforeEach(() => {
  estimate.mockReset().mockResolvedValue({ estimate_credits: 8, reserved_credits: 12, pages: [3, 7] });
  redraw.mockReset().mockResolvedValue({ status: "queued", jobs: [{ page_number: 3, job: { id: "j3" } }, { page_number: 7, job: { id: "j7" } }] });
});

it("names what changed and redraws only the confirmed pages after showing the estimate", async () => {
  const onQueued = vi.fn();
  render(<QueryClientProvider client={new QueryClient()}><I18nProvider>
    <OutOfDatePages project="demo" redraws={redraws} onQueued={onQueued} />
  </I18nProvider></QueryClientProvider>);

  const notice = screen.getByRole("region", { name: "Pages out of date" });
  expect(within(notice).getByText(/Drawn before these Story Bible or Cast entries changed: Carl \(Cast image changed\); Key \(description changed\)\./)).toBeTruthy();
  expect(within(notice).getByText(/Pages 3, 7/)).toBeTruthy();
  expect(redraw).not.toHaveBeenCalled();

  await userEvent.click(within(notice).getByRole("button", { name: "Redraw 2 pages" }));
  const dialog = await screen.findByRole("alertdialog");
  await within(dialog).findByText(/8/);
  await userEvent.click(within(dialog).getByRole("button", { name: "Redraw 2 pages" }));

  expect(redraw).toHaveBeenCalledWith("demo", [3, 7]);
  expect(onQueued).toHaveBeenCalledWith([{ page_number: 3, job: { id: "j3" } }, { page_number: 7, job: { id: "j7" } }]);
});

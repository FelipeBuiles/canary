import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { FeedbackButton } from "../components/FeedbackButton";

const mocks = vi.hoisted(() => ({ user: { id: "alice" }, fetch: vi.fn() }));
vi.mock("../hooks/useAuth", () => ({ useAuth: () => ({ user: mocks.user }) }));
vi.mock("../api/client", () => ({ apiFetch: mocks.fetch }));
beforeEach(() => { mocks.user = { id: "alice" }; mocks.fetch.mockReset(); });

it("keeps a retry receipt for unchanged feedback and changes it after an edit", async () => {
  mocks.fetch.mockRejectedValue(new Error("network"));
  render(<FeedbackButton />);
  fireEvent.click(screen.getByText("GIVE FEEDBACK"));
  fireEvent.change(screen.getByLabelText("Your feedback"), { target: { value: "I could not find export" } });
  fireEvent.click(screen.getByText("Send feedback"));
  await screen.findByRole("alert");
  const first = JSON.parse(mocks.fetch.mock.calls[0][1].body);
  fireEvent.click(screen.getByText("Send feedback"));
  await waitFor(() => expect(mocks.fetch).toHaveBeenCalledTimes(2));
  await screen.findByRole("alert");
  expect(JSON.parse(mocks.fetch.mock.calls[1][1].body).id).toBe(first.id);
  fireEvent.change(screen.getByLabelText("Your feedback"), { target: { value: "Export needs a clearer button" } });
  mocks.fetch.mockResolvedValue({});
  fireEvent.click(screen.getByText("Send feedback"));
  await screen.findByRole("status");
  expect(JSON.parse(mocks.fetch.mock.calls[2][1].body).id).not.toBe(first.id);
});

it("does not expose another account's feedback draft", () => {
  const view = render(<FeedbackButton />);
  fireEvent.click(screen.getByText("GIVE FEEDBACK"));
  fireEvent.change(screen.getByLabelText("Your feedback"), { target: { value: "Alice private draft" } });
  mocks.user = { id: "bob" };
  view.rerender(<FeedbackButton />);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.click(screen.getByText("GIVE FEEDBACK"));
  expect((screen.getByLabelText("Your feedback") as HTMLTextAreaElement).value).toBe("");
});

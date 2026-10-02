import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";
import { TesterTracker } from "../components/TesterTracker";
import { operatorFetch } from "../api/operator";
vi.mock("../api/operator", () => ({ operatorFetch: vi.fn() }));
const api = vi.mocked(operatorFetch);
const connection = { baseUrl: "", token: "private-token" };
beforeEach(() => api.mockReset());
function send(frame: HTMLIFrameElement, data: object, source: MessageEventSource | null = frame.contentWindow) {
  act(() => window.dispatchEvent(new MessageEvent("message", { source, data: { tracker: true, id: 1, ...data } })));
}
test("sandbox never receives the token and ignores foreign messages", async () => {
  render(<TesterTracker connection={connection} />);
  const frame = screen.getByTitle("Tester session tracker") as HTMLIFrameElement;
  expect(frame.getAttribute("sandbox")).toBe("allow-scripts allow-forms");
  expect(frame.srcdoc).not.toContain(connection.token);
  expect(frame.srcdoc).toContain("connect-src 'none'");
  send(frame, { action: "load" }, window);
  await act(async () => {});
  expect(api).not.toHaveBeenCalled();
});
test("host persists edits with loaded revisions and returns confirmed snapshots", async () => {
  api.mockResolvedValueOnce({ people: [{ id: "one", revision: 2, data: { handle: "Writer" } }], sessions: [], notes: [], findings: [] });
  api.mockResolvedValueOnce({ id: "one", revision: 3, data: { handle: "Updated" } });
  render(<TesterTracker connection={connection} />);
  const frame = screen.getByTitle("Tester session tracker") as HTMLIFrameElement;
  const reply = vi.spyOn(frame.contentWindow!, "postMessage");
  send(frame, { action: "load" });
  await waitFor(() => expect(reply).toHaveBeenCalled());
  send(frame, { action: "write", collection: "people", recordId: "one", mode: "update", data: { handle: "Updated" } });
  await waitFor(() => expect(api).toHaveBeenCalledTimes(2));
  expect(JSON.parse(api.mock.calls[1][2]!.body as string)).toEqual({ mode: "update", data: { handle: "Updated" }, expected_revision: 2 });
  await waitFor(() => expect(reply).toHaveBeenLastCalledWith(expect.objectContaining({ result: expect.objectContaining({ people: [{ id: "one", handle: "Updated" }] }) }), "*"));
});
test("save errors reach the tracker instead of confirming persistence", async () => {
  api.mockRejectedValueOnce(new Error("Storage unavailable"));
  render(<TesterTracker connection={connection} />);
  const frame = screen.getByTitle("Tester session tracker") as HTMLIFrameElement;
  const reply = vi.spyOn(frame.contentWindow!, "postMessage");
  send(frame, { action: "load" });
  await waitFor(() => expect(reply).toHaveBeenCalledWith({ tracker: true, id: 1, error: "Storage unavailable" }, "*"));
});

test("disconnected storage displays an error and rejects edits before loading", async () => {
  api.mockRejectedValueOnce(Object.assign(new Error("Not Found"), { status: 404 }));
  render(<TesterTracker connection={connection} />);
  const frame = screen.getByTitle("Tester session tracker") as HTMLIFrameElement;
  send(frame, { action: "load" });
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("updated backend"));
  send(frame, { action: "write", collection: "people", recordId: "new", mode: "set", data: { handle: "Draft" } });
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Storage is disconnected"));
  expect(api).toHaveBeenCalledTimes(1);
});
test("conflicts retain the last confirmed revision and show a visible error", async () => {
  api.mockResolvedValueOnce({ people: [{ id: "one", revision: 2, data: { handle: "Writer" } }] });
  api.mockRejectedValueOnce(new Error("Record changed. Reload before saving."));
  api.mockResolvedValueOnce({ people: [{ id: "one", revision: 3, data: { handle: "Other operator" } }] });
  render(<TesterTracker connection={connection} />);
  const frame = screen.getByTitle("Tester session tracker") as HTMLIFrameElement;
  const reply = vi.spyOn(frame.contentWindow!, "postMessage");
  send(frame, { action: "load" });
  await waitFor(() => expect(reply).toHaveBeenCalled());
  send(frame, { action: "write", collection: "people", recordId: "one", mode: "update", data: { handle: "Draft" } });
  await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Reload before saving"));
  send(frame, { action: "load" });
  await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  expect(reply).toHaveBeenLastCalledWith(expect.objectContaining({result: expect.objectContaining({people: [{id:"one", handle:"Other operator"}]})}), "*");
});

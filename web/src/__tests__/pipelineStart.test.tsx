import { useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, apiFetch } from "../api/client";
import type * as ApiClient from "../api/client";
import { useProjectStatus } from "../api/queries";
import { useRunAction } from "../hooks/useRunAction";
import { usePipelineStore } from "../store/pipeline";

vi.mock("../api/client", async (original) => ({ ...await original<typeof ApiClient>(), apiFetch: vi.fn() }));
const fetchMock = vi.mocked(apiFetch);
const connect = vi.fn();
let finishRequest: ((accepted: boolean) => void) | undefined;
let running = false;

beforeEach(() => {
  running = false;
  finishRequest = undefined;
  connect.mockReset();
  usePipelineStore.setState({ connect });
  fetchMock.mockImplementation(async (path) => {
    if (path.includes("/run?")) return new Promise((resolve, reject) => {
      finishRequest = (accepted) => {
        running = accepted;
        if (accepted) resolve({ status: "started", stage: "adapt" });
        else reject(new ApiError(409, "Approval requires an approved adaptation brief"));
      };
    });
    if (path.endsWith("/status")) return {
      id: "demo", is_running: running,
      stages: { adapt: { status: running ? "running" : "pending" } },
    };
    throw new Error(`Unexpected request: ${path}`);
  });
});
afterEach(() => usePipelineStore.setState(usePipelineStore.getInitialState()));

function StartControl() {
  const { handleRun, isPending } = useRunAction();
  const [error, setError] = useState("");
  return <>
    <button disabled={isPending} onClick={() => handleRun("demo", "adapt", {
      onError: (failure) => setError(failure.message),
    })}>{isPending ? "Starting…" : "Start this step"}</button>
    {error && <p role="alert">{error}</p>}
  </>;
}
function Room() {
  const { data } = useProjectStatus("demo");
  if (!data) return <p>Loading</p>;
  return data.stages.adapt.status === "running" ? <p>Work is running</p> : <StartControl />;
}
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(<QueryClientProvider client={client}><Room /></QueryClientProvider>);
}

it("keeps the start control mounted through admission and shows a rejection", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Start this step" }));
  await waitFor(() => expect(finishRequest).toBeTypeOf("function"));
  expect(screen.queryByText("Work is running")).toBeNull();
  expect((screen.getByRole("button", { name: "Starting…" }) as HTMLButtonElement).disabled).toBe(true);
  await act(async () => finishRequest!(false));
  expect((await screen.findByRole("alert")).textContent).toContain("Approval requires an approved adaptation brief");
  expect(screen.getByRole("button", { name: "Start this step" })).toBeTruthy();
  expect(connect).not.toHaveBeenCalled();
});

it("switches to running and connects progress only after the server accepts", async () => {
  setup();
  fireEvent.click(await screen.findByRole("button", { name: "Start this step" }));
  await waitFor(() => expect(finishRequest).toBeTypeOf("function"));
  expect(screen.queryByText("Work is running")).toBeNull();
  await act(async () => finishRequest!(true));
  expect(await screen.findByText("Work is running")).toBeTruthy();
  expect(connect).toHaveBeenCalledWith("demo");
});

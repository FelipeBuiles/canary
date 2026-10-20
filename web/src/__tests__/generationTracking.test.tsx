import { describe, expect, it } from "vitest";
import type { GenerationJob } from "../types/api";
import { generationStatus, isGenerationActive, isGenerationTerminal } from "../lib/generationTracking";

const job = (overrides: Partial<GenerationJob> = {}): GenerationJob => ({ id: "one", project_name: "p", kind: "complete_page_draw", label: "", payload: {}, status: "queued", queue_position: null, queued_at: "2026-10-17T01:00:00Z", started_at: null, finished_at: null, error: null, ...overrides });
describe("generation subject policy", () => {
  it.each(["character_ref", "location_plate", "prop_ref", "style_sample", "style_validation", "style_suggest", "complete_page_draw", "lettering_translation"])("selects newest %s admission and lets polling settle it", kind => {
    const admitted = job({ kind });
    expect(generationStatus({ kind }, [], admitted)).toBe(admitted);
    const settled = { ...admitted, status: "complete" as const };
    expect(generationStatus({ kind }, [settled, job({ kind: "other" })], admitted)).toBe(settled);
    const newer = job({ kind, id: "new", queued_at: "2026-10-17T02:00:00Z" });
    expect(generationStatus({ kind }, [newer, settled], admitted)).toBe(newer);
  });
  it.each(["queued", "running", "complete", "failed", "cancelled"] as const)("classifies %s consistently", status => {
    const value = job({ status });
    expect(isGenerationActive(value)).toBe(["queued", "running"].includes(status));
    expect(isGenerationTerminal(value)).toBe(["complete", "failed", "cancelled"].includes(status));
  });
  it("filters obsolete styles, appearance identities and page revisions before latest-wins", () => {
    const current = job({ payload: { char_id: "a:state" }, reference_style_hash: "current" });
    const stale = job({ ...current, id: "stale", reference_style_hash: "old", queued_at: "2026-10-17T02:00:00Z" });
    expect(generationStatus({ identity: "char_id", value: "a:state", currentStyleHash: "current" }, [current, stale])).toBe(current);
    expect(generationStatus({ identity: "char_id", value: "b:state" }, [current])).toBeNull();
    expect(generationStatus({ currentPage: true }, [job({ is_current_page: false })])).toBeNull();
  });
});

import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, vi } from "vitest";
import { useGenerationTracking } from "../hooks/useGenerationTracking";
import { apiFetch } from "../api/client";
import { invalidateGenerationResult } from "../api/generationTracking";
const server = vi.hoisted(() => ({ jobs: [] as GenerationJob[], admitted: null as GenerationJob | null, reads: vi.fn() }));
vi.mock("../api/client", async importOriginal => ({ ...await importOriginal<typeof import("../api/client")>(), apiFetch: async (path: string, options?: RequestInit) => { server.reads(path, options); return options?.method === "POST" ? { job: server.admitted } : { jobs: server.jobs }; } }));
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0; server.reads.mockClear(); server.jobs = []; });
it.each(["character_ref_regen", "location_plate_regen", "prop_ref_regen", "style_sample", "style_validation", "style_suggest", "complete_page_draw", "lettering_translation"])("observes %s admission and terminal evidence at the fetch seam", async kind => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const view = renderHook(() => useGenerationTracking("p"), { wrapper });
  await waitFor(() => expect(view.result.current.data).toEqual({ jobs: [] }));
  const admitted = job({ kind });
  server.admitted = admitted;
  await act(async () => { await view.result.current.start({ kind }, () => apiFetch<{ job: GenerationJob }>("/projects/p/start", { method: "POST", paidAction: true })); });
  expect(server.reads.mock.calls.filter(([, options]) => options?.method === "POST")).toHaveLength(1);
  await waitFor(() => expect(view.result.current.status({ kind })?.id).toBe(admitted.id));
  expect(client.getQueryData<GenerationJob[]>(["project", "p", "generation-admissions"])).toContainEqual(admitted);
  server.jobs = [{ ...admitted, status: "cancelled" }];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "p", "generation-jobs"] }); });
  await waitFor(() => expect(isGenerationTerminal(view.result.current.status({ kind }))).toBe(true));
  client.setQueryData(["project", "p", "status"], {});
  invalidateGenerationResult(client, "p", server.jobs[0]);
  expect(client.getQueryState(["project", "p", "status"])?.isInvalidated).toBe(true);
});

it("keeps an admission across an empty poll and retires it once the server acknowledges it", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const view = renderHook(() => useGenerationTracking("p"), { wrapper });
  await waitFor(() => expect(view.result.current.data?.jobs).toEqual([]));
  const admitted = job();
  await act(async () => { await view.result.current.start({ kind: admitted.kind }, async () => ({ job: admitted })); });
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "p", "generation-jobs"] }); });
  await waitFor(() => expect(view.result.current.status({ kind: admitted.kind })?.id).toBe(admitted.id));
  server.jobs = [{ ...admitted, status: "complete" }];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "p", "generation-jobs"] }); });
  await waitFor(() => expect(view.result.current.status({ kind: admitted.kind })?.status).toBe("complete"));
  expect(client.getQueryData(["project", "p", "generation-admissions"])).toEqual([]);
  server.jobs = [];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "p", "generation-jobs"] }); });
  await waitFor(() => expect(view.result.current.status({ kind: admitted.kind })).toBeNull());
});

import { InsufficientCreditsError } from "../api/client";
import { useInsufficientCreditsStore } from "../store/insufficientCredits";
it("offers credit recovery for the same action without retrying failed or ambiguous submissions", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const view = renderHook(() => useGenerationTracking("p"), { wrapper });
  const error = new InsufficientCreditsError({ balance_credits: 1, required_credits: 5, shortfall_credits: 4, stage: null, action: "draw", message: "Need credits" });
  const submit = vi.fn(async () => { throw error; });
  const retry = vi.fn();
  await act(async () => { await expect(view.result.current.start({ kind: "complete_page_draw" }, submit, { actionLabel: "Draw page", onRetry: retry })).rejects.toBe(error); });
  expect(submit).toHaveBeenCalledOnce();
  expect(retry).not.toHaveBeenCalled();
  expect(useInsufficientCreditsStore.getState().actionLabel).toBe("Draw page");
  expect(useInsufficientCreditsStore.getState().onRetry).toBe(retry);
  useInsufficientCreditsStore.getState().close();
  const ambiguous = vi.fn(async () => { throw new Error("Connection interrupted"); });
  await act(async () => { await expect(view.result.current.start({ kind: "complete_page_draw" }, ambiguous)).rejects.toThrow("Connection interrupted"); });
  expect(ambiguous).toHaveBeenCalledOnce();
  expect(useInsufficientCreditsStore.getState().open).toBe(false);
});

it("refreshes evidence only for jobs this client saw active, not finished history", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  server.jobs = [job({ id: "old", status: "complete" }), job({ id: "live", status: "running" })];
  client.setQueryData(["project", "p", "status"], {});
  const view = renderHook(() => useGenerationTracking("p"), { wrapper });
  await waitFor(() => expect(view.result.current.data?.jobs).toHaveLength(2));
  expect(client.getQueryState(["project", "p", "status"])?.isInvalidated).toBe(false);
  server.jobs = [job({ id: "old", status: "complete" }), job({ id: "live", status: "complete" })];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "p", "generation-jobs"] }); });
  await waitFor(() => expect(client.getQueryState(["project", "p", "status"])?.isInvalidated).toBe(true));
});

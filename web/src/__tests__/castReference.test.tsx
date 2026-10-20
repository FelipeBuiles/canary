import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { useCastReference } from "../hooks/useCastReference";
import type { GenerationJob } from "../types/api";
const server = vi.hoisted(() => ({ fetch: vi.fn(), jobs: [] as GenerationJob[] }));
vi.mock("../api/client", async importOriginal => ({ ...await importOriginal<typeof import("../api/client")>(), apiFetch: (...args: unknown[]) => server.fetch(...args) }));
const clients: QueryClient[] = [];
afterEach(() => { cleanup(); clients.forEach(client => client.clear()); clients.length = 0; server.fetch.mockReset(); server.jobs = []; });
it.each([
  ["character", undefined, "regen-ref?char_id=entity", "char_id"],
  ["location", undefined, "regen-plate?loc_id=entity", "loc_id"],
  ["prop", undefined, "regen-prop?prop_id=entity", "prop_id"],
  ["character", "injured", "regen-state-ref?char_id=entity&state_id=injured", "char_id"],
  ["location", "burned", "locations/entity/states/burned/regenerate", "loc_id"],
] as const)("admits and recovers %s %s through the fetch seam", async (kind, stateId, path, identity) => {
  const admitted: GenerationJob = { id: "job", kind: "reference_regen", project_name: "project", label: "", status: "queued", payload: { [identity]: stateId ? `entity:${stateId}` : "entity" }, queued_at: "2026-10-17T01:00:00Z", started_at: null, finished_at: null, error: null, queue_position: null };
  server.fetch.mockImplementation(async (_path: string, options?: RequestInit) => options?.method === "POST" ? { job: admitted } : _path.endsWith("/jobs") ? { jobs: server.jobs } : { estimate_credits: 2 });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const view = renderHook(() => useCastReference("project", kind, "entity", stateId), { wrapper });
  await act(async () => view.result.current.regenerate());
  await waitFor(() => expect(view.result.current.activeJob?.id).toBe("job"));
  const submissions = server.fetch.mock.calls.filter(([, options]) => options?.method === "POST");
  expect(submissions).toHaveLength(1);
  expect(submissions[0][0]).toBe(`/projects/project/${path}`);
  expect(submissions[0][1].paidAction).toBe(true);
  server.jobs = [{ ...admitted, status: "cancelled" }];
  await act(async () => { await client.invalidateQueries({ queryKey: ["project", "project", "generation-jobs"] }); });
  await waitFor(() => expect(view.result.current.activeJob).toBeNull());
  expect(view.result.current.regenError).toBeNull();
});

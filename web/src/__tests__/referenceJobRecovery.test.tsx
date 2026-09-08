import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { useReferenceJob } from "../hooks/useReferenceJob";
import type { GenerationJob } from "../types/api";
import type * as PipelineApi from "../api/pipeline";

const server = vi.hoisted(() => ({ jobs: [] as GenerationJob[], reads: vi.fn() }));
vi.mock("../api/pipeline", async (importOriginal) => ({
  ...await importOriginal<typeof PipelineApi>(),
  getGenerationJobs: async () => { server.reads(); return { jobs: server.jobs }; },
}));

const clients: QueryClient[] = [];
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; server.reads.mockClear(); });

function observe(identity: "char_id" | "loc_id" | "prop_id", stateId?: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  return { client, ...renderHook(() => useReferenceJob("project", identity, "entity", stateId), { wrapper }) };
}

it.each(["char_id", "loc_id", "prop_id"] as const)("resumes %s jobs after leaving and returning, then refreshes metadata on failure", async (identity) => {
  server.jobs = [{ id: "job", project_name: "project", kind: "reference_regen", label: "Reference", payload: { [identity]: "entity" }, status: "running", queue_position: null, queued_at: "2026-09-07T10:00:00Z", started_at: null, finished_at: null, error: null }];
  const first = observe(identity);
  await waitFor(() => expect(first.result.current.activeJob?.id).toBe("job"));
  first.unmount();
  const second = observe(identity);
  await waitFor(() => expect(second.result.current.activeJob?.id).toBe("job"));
  second.client.setQueryData(["project", "project", "image-generation-meta", "ref.png"], { old: true });
  server.jobs = [{ ...server.jobs[0], status: "failed", error: "Provider rejected reference" }];
  await act(async () => { await second.client.invalidateQueries({ queryKey: ["project", "project", "generation-jobs"] }); });
  await waitFor(() => expect(second.result.current.regenError).toBe("Provider rejected reference"));
  expect(second.result.current.activeJob).toBeNull();
  expect(second.client.getQueryState(["project", "project", "image-generation-meta", "ref.png"])?.isInvalidated).toBe(true);
  act(() => second.result.current.setImgFailed(true));
  expect(second.result.current.imgFailed).toBe(true);
  const failedImageToken = second.result.current.timestamp;
  server.jobs = [{ ...server.jobs[0], id: "replacement", status: "complete", queued_at: "2026-09-07T10:01:00Z", finished_at: "2026-09-07T10:02:00Z", error: null }];
  await act(async () => { await second.client.invalidateQueries({ queryKey: ["project", "project", "generation-jobs"] }); });
  await waitFor(() => expect(second.result.current.regenError).toBeNull());
  expect(second.result.current.imgFailed).toBe(false);
  expect(second.result.current.timestamp).not.toBe(failedImageToken);
});

it("keeps alternate appearance jobs separate from base references", async () => {
  server.jobs = [{ id: "state-job", project_name: "project", kind: "character_ref_regen", label: "Appearance", payload: { char_id: "entity:injured" }, status: "running", queue_position: null, queued_at: "2026-09-07T10:00:00Z", started_at: null, finished_at: null, error: null }];
  const base = observe("char_id");
  const state = observe("char_id", "injured");
  await waitFor(() => expect(state.result.current.activeJob?.id).toBe("state-job"));
  expect(base.result.current.activeJob).toBeNull();
});

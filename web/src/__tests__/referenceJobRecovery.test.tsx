import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { useReferenceJob } from "../hooks/useReferenceJob";
import { useSetActiveStyle } from "../api/queries";
import type { GenerationJob } from "../types/api";
import type * as PipelineApi from "../api/pipeline";

const server = vi.hoisted(() => ({ jobs: [] as GenerationJob[], reads: vi.fn(), styleHash: undefined as string | undefined, styleChanged: true }));
vi.mock("../api/pipeline", async (importOriginal) => ({
  ...await importOriginal<typeof PipelineApi>(),
  getGenerationJobs: async () => { server.reads(); return { jobs: server.jobs, current_reference_style_hash: server.styleHash }; },
}));
vi.mock("../api/styles", async (importOriginal) => ({
  ...await importOriginal<typeof import("../api/styles")>(),
  setActiveStyle: async () => {
    if (server.styleChanged) server.styleHash = "new-style";
    return { status: "updated", id: "new", index: 2, style_template: "new wash", style_changed: server.styleChanged };
  },
}));

const clients: QueryClient[] = [];
afterEach(() => { clients.forEach((client) => client.clear()); clients.length = 0; server.reads.mockClear(); server.styleHash = undefined; server.styleChanged = true; });

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

it("recovers a failed appearance correction draft without leaking it onto the base reference", async () => {
  const instruction = "Restore the canonical silhouette in this appearance.";
  const reason = "The requested change contradicts this appearance's anchor.";
  server.jobs = [{ id: "correction", project_name: "project", kind: "character_ref_regen", label: "Appearance", payload: { char_id: "entity:injured", instruction }, status: "failed", queue_position: null, queued_at: "2026-09-07T10:00:00Z", started_at: null, finished_at: "2026-09-07T10:01:00Z", error: reason, user_message: reason }];
  const base = observe("char_id");
  const state = observe("char_id", "injured");
  await waitFor(() => expect(state.result.current.regenError).toBe(reason));
  expect(state.result.current.instructionDraft).toBe(instruction);
  expect(base.result.current.regenError).toBeNull();
  expect(base.result.current.instructionDraft).toBe("");
});

it.each(["char_id", "loc_id", "prop_id"] as const)("drops old-style %s errors and drafts, then shows a failure in the new style", async (identity) => {
  server.styleHash = "old-style";
  const oldJob: GenerationJob = { id: "old", project_name: "project", kind: "reference_regen", label: "Reference", payload: { [identity]: "entity:injured", instruction: "Old correction" }, status: "failed", queue_position: null, queued_at: "2026-09-07T10:00:00Z", started_at: null, finished_at: "2026-09-07T10:01:00Z", error: "Old failure", reference_style_hash: "old-style" };
  server.jobs = [oldJob];
  const view = observe(identity, "injured");
  await waitFor(() => expect(view.result.current.regenError).toBe("Old failure"));
  act(() => { view.result.current.setActiveJob(oldJob); view.result.current.setImgFailed(true); });
  const oldTimestamp = view.result.current.timestamp;
  server.styleHash = "new-style";
  await act(async () => { await view.client.invalidateQueries({ queryKey: ["project", "project", "generation-jobs"] }); });
  await waitFor(() => expect(view.result.current.regenError).toBeNull());
  expect(view.result.current.instructionDraft).toBe("");
  expect(view.result.current.activeJob).toBeNull();
  expect(view.result.current.imgFailed).toBe(false);
  expect(view.result.current.timestamp).not.toBe(oldTimestamp);
  view.unmount();
  const readsBeforeRemount = server.reads.mock.calls.length;
  const remounted = observe(identity, "injured");
  await waitFor(() => expect(server.reads.mock.calls.length).toBeGreaterThan(readsBeforeRemount));
  expect(remounted.result.current.regenError).toBeNull();
  server.jobs = [oldJob, { ...oldJob, id: "new", reference_style_hash: "new-style", error: "New failure", queued_at: "2026-09-07T11:00:00Z" }];
  await act(async () => { await remounted.client.invalidateQueries({ queryKey: ["project", "project", "generation-jobs"] }); });
  await waitFor(() => expect(remounted.result.current.regenError).toBe("New failure"));
});

it.each([true, false])("refreshes every project scope and clears old correction submission errors only when the style changes (%s)", async (changed) => {
  server.styleHash = "old-style";
  server.styleChanged = changed;
  server.jobs = [];
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  clients.push(client);
  const keys = ["project", "project~part_0001", "project~part_0002"].map((scope) => ["project", scope, "cast-freshness"]);
  for (const key of keys) client.setQueryData(key, { old: true });
  const cache = client.getMutationCache();
  const correction = cache.build(client, { mutationKey: ["reference-instruction", "char_id"], mutationFn: async () => { throw new Error("Old submission failure"); } });
  await correction.execute({ project: "project~part_0001", charId: "entity", instruction: "Old draft" }).catch(() => {});
  const unrelated = cache.build(client, { mutationKey: ["reference-instruction", "char_id"], mutationFn: async () => ({}) });
  await unrelated.execute({ project: "other", charId: "entity", instruction: "Unrelated draft" });
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const view = renderHook(() => ({ reference: useReferenceJob("project~part_0001", "char_id", "entity"), style: useSetActiveStyle() }), { wrapper });
  await waitFor(() => expect(view.result.current.reference.regenError).toBe("Old submission failure"));
  await act(async () => { await view.result.current.style.mutateAsync({ project: "project~part_0002", id: "new" }); });
  await waitFor(() => expect(view.result.current.reference.regenError).toBe(changed ? null : "Old submission failure"));
  expect(view.result.current.reference.instructionDraft).toBe(changed ? "" : "Old draft");
  for (const key of keys) expect(client.getQueryState(key)?.isInvalidated).toBe(changed);
  expect(cache.getAll()).toContain(unrelated);
});

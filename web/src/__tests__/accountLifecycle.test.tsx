import { act, render, screen, waitFor } from "@testing-library/react";
import { QueryClientProvider, useQuery } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";
import { signOut, useAuth } from "../hooks/useAuth";
import { queryClient } from "../api/queryClient";
import { useStyleGenStore } from "../store/styleGen";
import { usePipelineStore } from "../store/pipeline";
import { useInsufficientCreditsStore } from "../store/insufficientCredits";
import type { Session } from "@supabase/supabase-js";

const auth = vi.hoisted(() => ({ callback: null as ((event: string, session: unknown) => void) | null }));
vi.mock("../lib/supabase", () => ({ supabase: { auth: {
  getSession: async () => ({ data: { session: null } }),
  signOut: () => new Promise(() => {}),
  onAuthStateChange: (callback: typeof auth.callback) => { auth.callback = callback; return { data: { subscription: { unsubscribe: vi.fn() } } }; },
} } }));
vi.mock("../telemetry", () => ({ setTelemetryUser: vi.fn() }));

function PrivateContent() {
  const { data } = useQuery({ queryKey: ["credits", "balance"], queryFn: async () => "fresh account", staleTime: Infinity });
  return <div>{data ?? "empty account"}</div>;
}
function AccountSurface() {
  const { user, loading } = useAuth();
  if (loading) return null;
  return <QueryClientProvider key={user?.id ?? "out"} client={queryClient}><PrivateContent /></QueryClientProvider>;
}

it("replaces every private cache and transient job/dialog state on account switch and signout", async () => {
  render(<AccountSurface />);
  await waitFor(() => expect(auth.callback).not.toBeNull());
  act(() => auth.callback!("SIGNED_IN", { user: { id: "alice" } } as Session));
  const aliceClient = queryClient;
  act(() => {
    aliceClient.setQueryData(["credits", "balance"], "Alice's balance");
    aliceClient.setQueryData(["projects"], ["Alice's private manuscript"]);
    useStyleGenStore.getState().add("same-project", [1]);
    usePipelineStore.setState({ events: [{ type: "stage_start", stage: "draw" }] });
    useInsufficientCreditsStore.setState({ open: true, onRetry: vi.fn() });
  });
  act(() => auth.callback!("SIGNED_IN", { user: { id: "bob" } } as Session));
  expect(screen.queryByText("Alice's balance")).toBeNull();
  expect(queryClient).not.toBe(aliceClient);
  expect(queryClient.getQueryData(["projects"])).toBeUndefined();
  expect(useStyleGenStore.getState().pending).toEqual({});
  expect(usePipelineStore.getState().events).toEqual([]);
  expect(useInsufficientCreditsStore.getState().onRetry).toBeNull();
  // A late optimistic rollback remains isolated even after the old cache was cleared.
  act(() => aliceClient.setQueryData(["credits", "balance"], "Alice's late rollback"));
  expect(screen.queryByText("Alice's late rollback")).toBeNull();
  const bobClient = queryClient;
  act(() => { void signOut(); });
  expect(queryClient).not.toBe(bobClient);
  expect(bobClient.getMutationCache().getAll()).toEqual([]);
});

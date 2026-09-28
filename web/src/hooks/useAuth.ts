import { useSyncExternalStore } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "../lib/supabase";
import { setTelemetryUser } from "../telemetry";
import { recordAccountSeen } from "../api/events";
import { clearAccountRequests } from "../lib/accountEpoch";
import { replaceAccountQueryClient } from "../api/queryClient";
import { usePipelineStore } from "../store/pipeline";
import { useStyleGenStore } from "../store/styleGen";
import { useInsufficientCreditsStore } from "../store/insufficientCredits";

let snapshot = { session: null as Session | null, user: null as Session["user"] | null, loading: true };
const listeners = new Set<() => void>();
let initialized = false;

function receiveSession(session: Session | null) {
  if (snapshot.user?.id !== session?.user.id) {
    clearAccountRequests(session?.user.id ?? null);
    usePipelineStore.getState().disconnect();
    usePipelineStore.getState().clearEvents();
    useStyleGenStore.setState({ pending: {}, jobIds: {}, statuses: {}, queuePositions: {} });
    useInsufficientCreditsStore.getState().close();
    replaceAccountQueryClient(session?.user.id ?? null);
    if (session) void recordAccountSeen();
  }
  snapshot = { session, user: session?.user ?? null, loading: false };
  setTelemetryUser(snapshot.user?.id ?? null);
  listeners.forEach((listener) => listener());
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  if (!initialized) {
    initialized = true;
    let authEventReceived = false;
    supabase.auth.onAuthStateChange((_event, session) => {
      authEventReceived = true;
      receiveSession(session);
    });
    void supabase.auth.getSession().then(({ data: { session } }) => {
      if (!authEventReceived) receiveSession(session);
    });
  }
  return () => { listeners.delete(listener); };
}

export function signOut() {
  receiveSession(null);
  return supabase.auth.signOut();
}

export function useAuth() {
  return useSyncExternalStore(subscribe, () => snapshot);
}

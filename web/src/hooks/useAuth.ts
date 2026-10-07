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
let cookieUpdate: Promise<void> = Promise.resolve();

function synchronizeCookie(session: Session | null): Promise<void> {
  // Serialize transitions so an older account/refresh cannot replace the
  // cookie after a newer account or logout has completed.
  const update = cookieUpdate.catch(() => {}).then(async () => {
    const response = await fetch(`/api/auth/${session ? "session" : "logout"}`, {
      method: "POST", credentials: "same-origin",
      headers: session ? { Authorization: `Bearer ${session.access_token}` } : {},
    });
    if (!response.ok) throw new Error("Sign out could not be completed. Try again.");
  });
  cookieUpdate = update;
  return update;
}

function receiveSession(session: Session | null) {
  if (snapshot.user?.id !== session?.user.id || snapshot.session?.access_token !== session?.access_token || snapshot.loading) {
    void synchronizeCookie(session).catch(() => {});
  }
  if (snapshot.user?.id !== session?.user.id) {
    clearAccountRequests(session?.user.id ?? null);
    usePipelineStore.getState().disconnect();
    usePipelineStore.getState().clearEvents();
    useStyleGenStore.setState({ pending: {}, jobIds: {}, statuses: {}, queuePositions: {} });
    useInsufficientCreditsStore.getState().close();
    replaceAccountQueryClient(session?.user.id ?? null);
    // OAuth completes first-touch metadata before recording the account milestone.
    if (session && window.location.pathname !== "/auth/callback") void recordAccountSeen();
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

export async function signOut() {
  // Abort old reads before expiring the cookie; keep the account visible if
  // the browser cannot reach logout, rather than claiming it succeeded.
  clearAccountRequests(null);
  const account = snapshot.user?.id;
  try {
    await synchronizeCookie(null);
  } catch (error) {
    clearAccountRequests(snapshot.user?.id ?? null);
    throw error;
  }
  if (snapshot.user?.id !== account) {
    await synchronizeCookie(snapshot.session);
    return { error: null };
  }
  receiveSession(null);
  return supabase.auth.signOut();
}

const serverSnapshot = { session: null, user: null, loading: true };

export function useAuth() {
  return useSyncExternalStore(subscribe, () => snapshot, () => serverSnapshot);
}

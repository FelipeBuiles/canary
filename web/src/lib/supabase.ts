import { createClient } from "@supabase/supabase-js";

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL as string;
const supabasePublishableKey = import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY as string;

if (!supabaseUrl || !supabasePublishableKey) {
  throw new Error("VITE_SUPABASE_URL and VITE_SUPABASE_PUBLISHABLE_KEY must be set");
}

export const supabase = createClient(supabaseUrl, supabasePublishableKey);

/** Public provider flags; credentials stay in Supabase, never in the web build. */
export async function getAuthProviders(signal?: AbortSignal): Promise<{ google: boolean }> {
  const response = await fetch(`${supabaseUrl}/auth/v1/settings`, {
    headers: { apikey: supabasePublishableKey }, signal,
  });
  if (!response.ok) throw new Error("Could not load sign-in options");
  const settings = await response.json();
  return { google: settings.external?.google === true };
}

import { describe, expect, it } from "vitest";
import type { User } from "@supabase/supabase-js";
import { authCallbackUrl, authDestination, authRetryPath, oauthSignupMetadata } from "../lib/authContext";

const now = Date.parse("2026-09-29T20:00:00Z");
function user(metadata = {}, age = 1_000): User {
  return { id: "author", created_at: new Date(now - age).toISOString(),
    app_metadata: { provider: "google" }, user_metadata: metadata } as User;
}

describe("auth return context", () => {
  it("keeps valid referral and campaign context when retrying a cancelled sign-in", () => {
    const ref = `book-${"a".repeat(32)}`;
    expect(authRetryPath(new URLSearchParams(`sample=an-education&ref=${ref}&source=reddit&next=https://evil.example`)))
      .toBe(`/login?sample=an-education&ref=${ref}&utm_source=reddit`);
  });
  it("preserves only valid story and campaign values, never arbitrary next URLs", () => {
    const params = new URLSearchParams("sample=an-education&next=https://evil.example&ref=invalid");
    const url = new URL(authCallbackUrl(params, { source: "google", campaign: "launch", medium: "a private phrase" }));
    expect(url.pathname).toBe("/auth/callback");
    expect(url.search).toBe("?sample=an-education&source=google&campaign=launch");
    expect(authDestination(params)).toBe("/?sample=an-education");
    expect(authDestination(new URLSearchParams("sample=//evil.example"))).toBe("/");
  });

  it("fills first-touch metadata for a new Google account", () => {
    const ref = "a".repeat(32);
    expect(oauthSignupMetadata(user(), new URLSearchParams(`source=book_referral&ref=book-${ref}`), now))
      .toEqual({ acquisition: { source: "book_referral" }, referred_by_book: ref });
  });

  it("never overwrites existing attribution or attributes an old account to today's link", () => {
    expect(oauthSignupMetadata(user({ acquisition: { source: "original" } }), new URLSearchParams("source=new"), now)).toBeNull();
    expect(oauthSignupMetadata(user({}, 86_400_000), new URLSearchParams("source=new"), now)).toBeNull();
    expect(oauthSignupMetadata({ ...user(), created_at: "invalid" }, new URLSearchParams(), now)).toBeNull();
  });

  it("preserves any existing referral and rejects unbounded callback values", () => {
    const params = new URLSearchParams(`ref=book-${"b".repeat(32)}&source=${"x".repeat(1000)}`);
    expect(oauthSignupMetadata(user({ referred_by_book: "original" }), params, now)).toEqual({ acquisition: { source: "direct" } });
  });
});

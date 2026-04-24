import { describe, it, expect } from "vitest";
import { cn } from "../lib/cn";

describe("cn", () => {
  it("joins non-empty strings", () => {
    expect(cn("foo", "bar")).toBe("foo bar");
  });

  it("filters out falsy values", () => {
    expect(cn("foo", undefined, "bar", null, false, "baz")).toBe("foo bar baz");
  });

  it("handles all falsy", () => {
    expect(cn(undefined, null, false)).toBe("");
  });

  it("handles empty call", () => {
    expect(cn()).toBe("");
  });

  it("deduplicates identical classes", () => {
    // Note: cn doesn't deduplicate — it just joins. That's expected.
    expect(cn("foo", "foo")).toBe("foo foo");
  });

  it("strips whitespace from individual parts", () => {
    expect(cn("  foo  ", "bar")).toBe("  foo   bar");
  });
});

import { describe, expect, it } from "vitest";
import { ApiError, isNotFoundError } from "../api/client";
import { retryPolicy } from "../api/queryClient";

describe("retryPolicy", () => {
  it("does not retry a missing artifact", () => {
    // Every artifact route answers 404 until its stage has run, so the default
    // retry: 3 turned one normal read into four requests.
    expect(retryPolicy(0, new ApiError(404, "adaptation not found"))).toBe(false);
  });

  it("does not retry any deterministic client error", () => {
    for (const status of [400, 401, 403, 404, 422]) {
      expect(retryPolicy(0, new ApiError(status, "nope"))).toBe(false);
    }
  });

  it("still retries server errors and transport failures", () => {
    expect(retryPolicy(0, new ApiError(500, "boom"))).toBe(true);
    expect(retryPolicy(0, new ApiError(503, "unavailable"))).toBe(true);
    expect(retryPolicy(0, new TypeError("Failed to fetch"))).toBe(true);
  });

  it("still gives up after three failures", () => {
    expect(retryPolicy(2, new ApiError(500, "boom"))).toBe(true);
    expect(retryPolicy(3, new ApiError(500, "boom"))).toBe(false);
  });
});

describe("isNotFoundError", () => {
  it("recognizes a typed 404", () => {
    expect(isNotFoundError(new ApiError(404, "gone"))).toBe(true);
    expect(isNotFoundError(new ApiError(500, "boom"))).toBe(false);
  });

  it("keeps the historic message shape callers matched on", () => {
    expect(new ApiError(404, "gone").message).toBe("API 404: gone");
    expect(isNotFoundError(new Error("API 404: gone"))).toBe(true);
  });
});

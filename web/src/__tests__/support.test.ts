import { describe, expect, it } from "vitest";
import { supportMailto } from "../lib/support";

describe("supportMailto", () => {
  it("includes only bounded safe diagnostics", () => {
    const href = supportMailto("hello@scenewright.ink", {
      releaseSha: "abc123",
      projectId: "project-1",
      stationOrStage: "draw",
      requestId: "request-1",
      errorCategory: "provider_timeout",
    });

    const url = new URL(href);
    const body = url.searchParams.get("body") ?? "";
    expect(body).toContain("Release: abc123");
    expect(body).toContain("Project: project-1");
    expect(body).toContain("Category: provider_timeout");
  });

  it("strips creative text and control characters from diagnostics", () => {
    const href = supportMailto("hello@scenewright.ink", {
      projectId: "project\nSECRET MANUSCRIPT",
    });

    const body = new URL(href).searchParams.get("body") ?? "";
    expect(body).not.toContain("SECRET MANUSCRIPT");
    expect(body).not.toContain("Project:");
  });
});

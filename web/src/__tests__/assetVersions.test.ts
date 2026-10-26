import { afterEach, describe, expect, it } from "vitest";
import { resetAssetVersions, setAssetVersions, versionedUrl } from "../lib/assetVersions";
import { thumbnailUrl } from "../components/cast/castAssets";
import { pageRenderPreviewUrl } from "../api/pages";

afterEach(resetAssetVersions);

describe("versioned image URLs", () => {
  it("adds the listed version to files, their thumbnails and page renders", () => {
    setAssetVersions("/api/projects/demo", { "refs/char 1/sheet.png": "a-1" });
    setAssetVersions("/api/projects/demo/parts/p1", { "draw/pages/page_004/render_002.png": "b-2" });

    expect(versionedUrl("/api/projects/demo/files/refs/char%201/sheet.png?t=3"))
      .toBe("/api/projects/demo/files/refs/char%201/sheet.png?t=3&v=a-1");
    expect(thumbnailUrl("/api/projects/demo/files/refs/char%201/sheet.png?t=3"))
      .toBe("/api/projects/demo/thumbnails/thumbnail/refs/char%201/sheet.png?t=3&v=a-1");
    expect(pageRenderPreviewUrl("demo~p1", 4, 2, "thumbnail"))
      .toBe("/api/projects/demo/parts/p1/pages/4/renders/2/preview/thumbnail?delivery=2&v=b-2");
  });

  it("is idempotent and leaves unlisted images to revalidate", () => {
    setAssetVersions("/api/projects/demo", { "plates/loc.png": "c-3" });
    const once = versionedUrl("/api/projects/demo/files/plates/loc.png");
    expect(versionedUrl(once)).toBe(once);
    // A part scope never borrows the series listing.
    expect(versionedUrl("/api/projects/demo/parts/p1/files/plates/loc.png")).toBe("/api/projects/demo/parts/p1/files/plates/loc.png");
    expect(versionedUrl("/api/projects/demo/files/plates/new.png")).toBe("/api/projects/demo/files/plates/new.png");
  });
});

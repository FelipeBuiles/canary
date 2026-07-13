import { describe, expect, it } from "vitest";
import { panelReframeHasSettled } from "../components/compose/panelReframe";
import type { ComicPage } from "../types/api";

function pageWithOffset(x: number | null, y: number | null): ComicPage {
  return {
    page_number: 1,
    panels: [{ id: "panel-1", image_offset_x: x, image_offset_y: y }] as ComicPage["panels"],
  } as ComicPage;
}

describe("panelReframeHasSettled", () => {
  const drag = {
    panelId: "panel-1",
    startOffsetX: 10,
    startOffsetY: 20,
    dx: 40,
    dy: -20,
    scale: 2,
  };

  it("keeps the optimistic crop while incoming page data still has the old position", () => {
    expect(panelReframeHasSettled(pageWithOffset(10, 20), drag)).toBe(false);
  });

  it("releases the optimistic crop once page data contains the committed position", () => {
    expect(panelReframeHasSettled(pageWithOffset(30, 10), drag)).toBe(true);
  });
});

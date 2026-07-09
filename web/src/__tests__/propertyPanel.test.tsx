import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PropertyPanel } from "../components/compose/PropertyPanel";
import type { ComicPage } from "../types/api";

const page: ComicPage = {
  page_number: 1,
  source_page_id: null,
  layout: "1",
  layout_mode: "grid",
  panels: [{
    id: "panel-1",
    planned_panel_id: null,
    image_path: "draw/panel.png",
    scene_id: "scene_001",
    panel_number: 1,
    importance: null,
    generation_mode: null,
    bubbles: [],
    sfx: [],
    image_offset_x: 32,
    image_offset_y: -16,
    image_scale: 1.5,
    grid_column: null,
    grid_row: null,
    x: null,
    y: null,
    width: null,
    height: null,
    clip_path: null,
    z_index: null,
    shape_intent: null,
  }],
};

describe("PropertyPanel panel reframing", () => {
  it("previews zoom locally and commits it when the range interaction ends", () => {
    const onPreviewPanelScale = vi.fn();
    const onCommitPanelScale = vi.fn();
    const onCenterPanelFrame = vi.fn();
    const onResetPanelFrame = vi.fn();

    render(
      <PropertyPanel
        page={page}
        selection={null}
        panelReframeId="panel-1"
        onUpdateBubble={vi.fn()}
        onUpdateSfx={vi.fn()}
        onDeleteElement={vi.fn()}
        onUnpin={vi.fn()}
        onCenterPanelFrame={onCenterPanelFrame}
        onResetPanelFrame={onResetPanelFrame}
        onPreviewPanelScale={onPreviewPanelScale}
        onCommitPanelScale={onCommitPanelScale}
      />,
    );

    const zoom = screen.getByRole("slider", { name: "Panel image zoom" });
    expect((zoom as HTMLInputElement).value).toBe("1.5");

    fireEvent.change(zoom, { target: { value: "1.8" } });
    expect(onPreviewPanelScale).toHaveBeenLastCalledWith("panel-1", 1.8);

    fireEvent.pointerUp(zoom);
    expect(onCommitPanelScale).toHaveBeenCalledWith("panel-1", 1.8);

    fireEvent.click(screen.getByRole("button", { name: "CENTER IMAGE" }));
    expect(onCenterPanelFrame).toHaveBeenCalledWith("panel-1");

    fireEvent.click(screen.getByRole("button", { name: "RESET FRAMING" }));
    expect(onPreviewPanelScale).toHaveBeenLastCalledWith("panel-1", 1);
    expect(onResetPanelFrame).toHaveBeenCalledWith("panel-1");
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ComicPage } from "../types/api";
import { PageEditor } from "../components/compose/PageEditor";

vi.mock("../components/compose/ScaledContainer", () => ({
  ScaledContainer: ({
    children,
    onScaleChange,
  }: {
    children: React.ReactNode;
    onScaleChange?: (scale: number) => void;
  }) => {
    onScaleChange?.(0.1);
    return <div>{children}</div>;
  },
}));

vi.mock("../components/compose/ComicPageCanvas", () => ({
  ComicPageCanvas: () => (
    <div data-panel-id="panel-1">
      <div data-id="bubble-1" data-editor-selectable>
        Move me
      </div>
    </div>
  ),
}));

const PAGE = {
  page_number: 1,
  panels: [
    {
      id: "panel-1",
      panel_number: 1,
      bubbles: [{ id: "bubble-1", text: "Move me", type: "speech", side: "left" }],
      sfx: [],
    },
  ],
} as unknown as ComicPage;

describe("PageEditor touch dragging", () => {
  it("captures a touch pointer and commits the dragged bubble position", () => {
    const onSelect = vi.fn();
    const onDragEnd = vi.fn();
    const { container } = render(
      <PageEditor
        page={PAGE}
        project="proj"
        zoom={1}
        onZoomChange={() => {}}
        selectedId={null}
        selectedType={null}
        reframePanelId={null}
        onSelect={onSelect}
        onDeselect={() => {}}
        onPanelReframeStart={() => {}}
        onPanelReframeDragEnd={() => {}}
        onDragEnd={onDragEnd}
      />,
    );

    const editor = container.querySelector<HTMLElement>(".page-editor")!;
    editor.setPointerCapture = vi.fn();
    editor.hasPointerCapture = vi.fn(() => true);
    editor.releasePointerCapture = vi.fn();

    const bubble = screen.getByText("Move me");
    fireEvent.pointerDown(bubble, { pointerId: 7, pointerType: "touch", clientX: 10, clientY: 15 });
    fireEvent.pointerMove(editor, { pointerId: 7, pointerType: "touch", clientX: 30, clientY: 45 });
    fireEvent.pointerUp(editor, { pointerId: 7, pointerType: "touch", clientX: 30, clientY: 45 });

    expect(onSelect).toHaveBeenCalledWith("panel-1", "bubble", "bubble-1");
    expect(editor.setPointerCapture).toHaveBeenCalledWith(7);
    expect(onDragEnd).toHaveBeenCalledWith("panel-1", "bubble", "bubble-1", 200, 300);
  });

  it("cleans up a cancelled touch gesture without saving it", () => {
    const onDragEnd = vi.fn();
    const { container } = render(
      <PageEditor
        page={PAGE}
        project="proj"
        zoom={1}
        onZoomChange={() => {}}
        selectedId={null}
        selectedType={null}
        reframePanelId={null}
        onSelect={() => {}}
        onDeselect={() => {}}
        onPanelReframeStart={() => {}}
        onPanelReframeDragEnd={() => {}}
        onDragEnd={onDragEnd}
      />,
    );

    const editor = container.querySelector<HTMLElement>(".page-editor")!;
    editor.setPointerCapture = vi.fn();
    editor.hasPointerCapture = vi.fn(() => true);
    editor.releasePointerCapture = vi.fn();

    fireEvent.pointerDown(screen.getByText("Move me"), {
      pointerId: 9,
      pointerType: "touch",
      clientX: 10,
      clientY: 15,
    });
    fireEvent.pointerCancel(editor, { pointerId: 9, pointerType: "touch" });

    expect(editor.releasePointerCapture).toHaveBeenCalledWith(9);
    expect(onDragEnd).not.toHaveBeenCalled();
  });
});

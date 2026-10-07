import { act, fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { resolvePage, type LetteringStyle, type PageLettering } from "@lettering-engine";
import { LetteringCanvas } from "../components/lettering/LetteringCanvas";
import { I18nProvider } from "../i18n";
import fixture from "./fixtures/lettering.json";

let frame: FrameRequestCallback;
const cancelFrame = vi.fn();
beforeEach(() => {
  vi.stubGlobal("PointerEvent", MouseEvent);
  vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => { frame = callback; return 1; }));
  vi.stubGlobal("cancelAnimationFrame", cancelFrame);
  cancelFrame.mockClear();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

function canvas() {
  const style = fixture.style as LetteringStyle;
  const state = resolvePage(fixture.state as PageLettering, style, text => text.length * 10);
  const preview = vi.fn(), commit = vi.fn(), cancel = vi.fn();
  const { container } = render(<I18nProvider><LetteringCanvas state={state} style={style} artUrl="/art.png"
    selected={state.elements[0].id} disabled={false} onArtReady={vi.fn()} select={vi.fn()} focusText={vi.fn()}
    begin={vi.fn()} preview={preview} commit={commit} cancel={cancel} change={vi.fn()} /></I18nProvider>);
  const page = container.querySelector<HTMLElement>(".lettering-page")!;
  vi.spyOn(page, "getBoundingClientRect").mockReturnValue({ width: 1000, height: 1500, left: 0, top: 0 } as DOMRect);
  const handle = container.querySelector<HTMLButtonElement>(".lettering-hit")!;
  handle.setPointerCapture = vi.fn();
  fireEvent.pointerDown(handle, { button: 0, clientX: 100, clientY: 100 });
  return { handle, preview, commit, cancel, initialX: state.elements[0].placement.x };
}

describe("lettering drag performance", () => {
  it("coalesces pointer moves and commits the final unpainted position", () => {
    const { handle, preview, commit, initialX } = canvas();
    fireEvent.pointerMove(handle, { clientX: 110, clientY: 100 });
    fireEvent.pointerMove(handle, { clientX: 120, clientY: 100 });
    expect(preview).not.toHaveBeenCalled();
    act(() => frame(1));
    expect(preview).toHaveBeenCalledOnce();
    expect(preview.mock.calls[0][1].placement.x).toBeCloseTo(initialX + .02);
    fireEvent.pointerMove(handle, { clientX: 130, clientY: 100 });
    fireEvent.pointerUp(handle);
    expect(preview).toHaveBeenCalledTimes(2);
    expect(preview.mock.calls[1][1].placement.x).toBeCloseTo(initialX + .03);
    expect(commit).toHaveBeenCalledOnce();
    expect(commit.mock.invocationCallOrder[0]).toBeGreaterThan(preview.mock.invocationCallOrder[1]);
  });

  it("discards pending previews when the gesture is cancelled", () => {
    const { handle, preview, commit, cancel } = canvas();
    fireEvent.pointerMove(handle, { clientX: 120, clientY: 100 });
    fireEvent.pointerCancel(handle);
    expect(cancelFrame).toHaveBeenCalledWith(1);
    act(() => frame(1));
    expect(preview).not.toHaveBeenCalled();
    expect(commit).not.toHaveBeenCalled();
    expect(cancel).toHaveBeenCalledOnce();
  });
});

import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { BeforeAfterWipe } from "../components/pages/BeforeAfterWipe";
import { Loupe } from "../components/ui/Loupe";

function rect(width: number, height: number): DOMRect {
  return { x: 0, y: 0, left: 0, top: 0, right: width, bottom: height, width, height, toJSON: () => ({}) } as DOMRect;
}

function wipe(visible: boolean) {
  return <I18nProvider><BeforeAfterWipe
    beforeSrc="/before.png" afterSrc="/after.png" beforeAlt="Page 4, revision 1" afterAlt="Page 4, revision 2"
    beforeLabel="BEFORE · 1" afterLabel="AFTER · 2" visible={visible} firstViewKey="book:4:1:2"
  /></I18nProvider>;
}

beforeEach(() => window.localStorage.clear());
afterEach(() => vi.restoreAllMocks());

describe("revision wipe", () => {
  it("splits the page by slider and by dragging the art", () => {
    window.localStorage.setItem("canary.revisionWipeSeen.book:4:1:2", "1");
    render(wipe(true));
    const before = screen.getByRole("img", { name: "Page 4, revision 1" });
    expect(before.style.clipPath).toBe("inset(0 50% 0 0)");
    fireEvent.change(screen.getByRole("slider", { name: "Before and after split" }), { target: { value: "30" } });
    expect(before.style.clipPath).toBe("inset(0 70% 0 0)");
    expect(screen.getByRole("slider").getAttribute("aria-valuetext")).toBe("30% before, 70% after");

    const surface = screen.getByTestId("revision-wipe");
    vi.spyOn(surface, "getBoundingClientRect").mockReturnValue(rect(200, 300));
    surface.setPointerCapture = vi.fn();
    fireEvent.pointerDown(surface, { clientX: 160, pointerId: 1 });
    expect(before.style.clipPath).toBe("inset(0 20% 0 0)");
  });

  it("sweeps once the first time a revision pair is opened", () => {
    const frames: FrameRequestCallback[] = [];
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => { frames.push(callback); return frames.length; });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    vi.spyOn(performance, "now").mockReturnValue(0);
    const view = render(wipe(false));
    expect(frames).toHaveLength(0);
    view.rerender(wipe(true));
    expect(frames).toHaveLength(1);
    const before = screen.getByRole("img", { name: "Page 4, revision 1" });
    act(() => frames.shift()!(0));
    expect(before.style.clipPath).toBe("inset(0 0% 0 0)");
    act(() => frames.shift()!(900));
    expect(before.style.clipPath).toBe("inset(0 50% 0 0)");
    view.unmount();
    render(wipe(true));
    expect(frames).toHaveLength(0);
  });
});

describe("loupe", () => {
  it("magnifies under the pointer while Alt is held and keeps pixel art crisp", () => {
    render(<I18nProvider><Loupe><img src="/proof.png" alt="Proof" /></Loupe></I18nProvider>);
    const image = screen.getByRole("img", { name: "Proof" });
    Object.defineProperty(image, "naturalWidth", { value: 100 });
    Object.defineProperty(image, "naturalHeight", { value: 125 });
    vi.spyOn(image, "getBoundingClientRect").mockReturnValue(rect(200, 250));
    const wrapper = image.parentElement!;
    vi.spyOn(wrapper, "getBoundingClientRect").mockReturnValue(rect(200, 250));

    fireEvent.pointerMove(wrapper, { clientX: 100, clientY: 100 });
    expect(screen.queryByTestId("loupe")).toBeNull();
    fireEvent.pointerMove(wrapper, { clientX: 100, clientY: 100, altKey: true });
    const loupe = screen.getByTestId("loupe");
    expect(loupe.style.backgroundSize).toBe("500px 625px");
    expect(loupe.style.backgroundPosition).toBe("-160px -160px");
    expect(loupe.style.imageRendering).toBe("pixelated");
    fireEvent.pointerLeave(wrapper);
    expect(screen.queryByTestId("loupe")).toBeNull();
  });
});

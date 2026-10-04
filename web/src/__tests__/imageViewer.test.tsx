import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { InspectButton } from "../components/ui/InspectButton";
import { centeredView, clampView, fitScale, zoomAt } from "../lib/zoomPan";

const image = { width: 1000, height: 1500 };
const stage = { width: 800, height: 600 };

describe("zoom geometry", () => {
  it("fits inside the padded stage and keeps the anchored image point still", () => {
    const fit = fitScale(image, stage);
    expect(fit).toBeCloseTo((600 - 32) / 1500);
    const start = centeredView(fit, image, stage);
    const anchor = { x: 400, y: 300 };
    const before = { x: (anchor.x - start.x) / start.scale, y: (anchor.y - start.y) / start.scale };
    const next = zoomAt(start, 1, anchor, image, stage);
    expect(next.scale).toBe(1);
    expect((anchor.x - next.x) / next.scale).toBeCloseTo(before.x);
    expect((anchor.y - next.y) / next.scale).toBeCloseTo(before.y);
  });

  it("centers an axis that fits and keeps image edges on stage otherwise", () => {
    expect(clampView({ scale: 0.2, x: -50, y: 999 }, image, stage)).toEqual({ scale: 0.2, x: 300, y: 150 });
    expect(clampView({ scale: 1, x: 50, y: -5000 }, image, stage)).toEqual({ scale: 1, x: 0, y: -900 });
  });

  it("clamps zoom between fit (or 1:1) and a deep close-up", () => {
    const fit = fitScale(image, stage);
    const start = centeredView(fit, image, stage);
    expect(zoomAt(start, 0.01, { x: 0, y: 0 }, image, stage).scale).toBe(fit);
    expect(zoomAt(start, 100, { x: 0, y: 0 }, image, stage).scale).toBe(8);
  });
});

describe("image viewer", () => {
  const natural = ["naturalWidth", "naturalHeight"].map((name) => [name, Object.getOwnPropertyDescriptor(HTMLImageElement.prototype, name)] as const);
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
      const rect = this.dataset.testid === "image-viewer-stage" ? stage : { width: 0, height: 0 };
      return { x: 0, y: 0, left: 0, top: 0, right: rect.width, bottom: rect.height, ...rect, toJSON: () => ({}) } as DOMRect;
    });
    Object.defineProperty(HTMLImageElement.prototype, "naturalWidth", { configurable: true, get: () => image.width });
    Object.defineProperty(HTMLImageElement.prototype, "naturalHeight", { configurable: true, get: () => image.height });
  });
  afterEach(() => {
    vi.restoreAllMocks();
    for (const [name, descriptor] of natural) if (descriptor) Object.defineProperty(HTMLImageElement.prototype, name, descriptor);
    document.body.style.overflow = "";
  });

  const pages = [
    { src: "/page-1.png", alt: "Page 1" },
    { src: "/page-2.png", alt: "Page 2", downloadable: false },
  ];

  async function openViewer(onParentClick = vi.fn()) {
    const user = userEvent.setup();
    render(<I18nProvider>
      <div onClick={onParentClick} onKeyDown={onParentClick}>
        <InspectButton images={pages} />
      </div>
    </I18nProvider>);
    await user.click(screen.getByRole("button", { name: "Zoom and inspect · Page 1" }));
    onParentClick.mockClear();
    const dialog = screen.getByRole("dialog", { name: "Image viewer · Page 1" });
    fireEvent.load(within(dialog).getByRole("img", { name: "Page 1" }));
    return { user, dialog, onParentClick };
  }

  it("zooms with the toolbar and keys, and returns to fit", async () => {
    const { user, dialog } = await openViewer();
    const level = within(dialog).getByRole("status", { name: "Zoom level" });
    const fitted = `${Math.round(fitScale(image, stage) * 100)}%`;
    expect(level.textContent).toBe(fitted);
    expect(within(dialog).getByRole("button", { name: "Fit to screen" }).getAttribute("aria-pressed")).toBe("true");

    await user.click(within(dialog).getByRole("button", { name: "Actual size" }));
    expect(level.textContent).toBe("100%");
    const art = within(dialog).getByRole("img", { name: "Page 1" });
    expect(art.style.transform).toContain("scale(1)");

    await user.click(within(dialog).getByRole("button", { name: "Zoom in" }));
    expect(level.textContent).toBe("150%");
    fireEvent.keyDown(within(dialog).getByTestId("image-viewer-stage"), { key: "0" });
    expect(level.textContent).toBe(fitted);

    fireEvent.wheel(within(dialog).getByTestId("image-viewer-stage"), { deltaY: -400, clientX: 400, clientY: 300 });
    expect(Number.parseInt(level.textContent!)).toBeGreaterThan(Number.parseInt(fitted));
  });

  it("double-click toggles a close-up and drag pans it", async () => {
    const { dialog } = await openViewer();
    const surface = within(dialog).getByTestId("image-viewer-stage");
    const art = within(dialog).getByRole("img", { name: "Page 1" });
    const tap = (x: number, y: number) => {
      fireEvent.pointerDown(surface, { pointerId: 1, clientX: x, clientY: y, button: 0, pointerType: "mouse" });
      fireEvent.pointerUp(surface, { pointerId: 1, clientX: x, clientY: y, pointerType: "mouse" });
    };
    tap(400, 300);
    tap(400, 300);
    expect(within(dialog).getByRole("status", { name: "Zoom level" }).textContent).toBe("100%");
    const before = art.style.transform;
    fireEvent.pointerDown(surface, { pointerId: 2, clientX: 400, clientY: 300, button: 0, pointerType: "mouse" });
    fireEvent.pointerMove(surface, { pointerId: 2, clientX: 300, clientY: 200, pointerType: "mouse" });
    fireEvent.pointerUp(surface, { pointerId: 2, clientX: 300, clientY: 200, pointerType: "mouse" });
    expect(art.style.transform).not.toBe(before);
    expect(screen.getByTestId("image-viewer-navigator")).toBeTruthy();
  });

  it("flips through a set, hides blind downloads, and keeps events from the opener", async () => {
    const { user, dialog, onParentClick } = await openViewer();
    expect(within(dialog).getByRole("link", { name: "Download image" }).getAttribute("href")).toBe("/page-1.png");
    fireEvent.keyDown(within(dialog).getByTestId("image-viewer-stage"), { key: "ArrowRight" });
    expect(screen.getByRole("dialog", { name: "Image viewer · Page 2" })).toBeTruthy();
    expect(within(dialog).queryByRole("link", { name: "Download image" })).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: "Previous image" }));
    expect(screen.getByRole("dialog", { name: "Image viewer · Page 1" })).toBeTruthy();
    expect(onParentClick).not.toHaveBeenCalled();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(document.activeElement).toBe(screen.getByRole("button", { name: "Zoom and inspect · Page 1" }));
  });
});

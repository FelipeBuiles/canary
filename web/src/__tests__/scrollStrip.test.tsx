import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ScrollStripControls } from "../components/ui/ScrollStrip";
import { useScrollStrip } from "../components/ui/useScrollStrip";
import { I18nProvider } from "../i18n";

function Strip() {
  const { attach: stripRef, ...strip } = useScrollStrip<HTMLDivElement>();
  return (
    <I18nProvider>
    <div className="relative">
      <ScrollStripControls strip={strip} />
      <div ref={stripRef} data-testid="strip">
        {Array.from({ length: 12 }, (_, index) => <button key={index} type="button">Item {index + 1}</button>)}
      </div>
    </div>
    </I18nProvider>
  );
}

/** jsdom has no layout: give the strip a viewport and content width. */
function size(element: HTMLElement, { client, scroll, left = 0 }: { client: number; scroll: number; left?: number }) {
  Object.defineProperty(element, "clientWidth", { configurable: true, value: client });
  Object.defineProperty(element, "scrollWidth", { configurable: true, value: scroll });
  element.scrollLeft = left;
  fireEvent.scroll(element);
}

describe("ScrollStrip", () => {
  it("shows no arrows while everything fits", () => {
    render(<Strip />);
    act(() => size(screen.getByTestId("strip"), { client: 600, scroll: 600 }));
    expect(screen.queryByTitle("Scroll left")).toBeNull();
    expect(screen.queryByTitle("Scroll right")).toBeNull();
  });

  it("offers an arrow on each side that still holds hidden items", () => {
    render(<Strip />);
    const strip = screen.getByTestId("strip");
    act(() => size(strip, { client: 300, scroll: 900 }));
    expect(screen.queryByTitle("Scroll left")).toBeNull();
    expect(screen.getByTitle("Scroll right")).toBeTruthy();

    act(() => size(strip, { client: 300, scroll: 900, left: 300 }));
    expect(screen.getByTitle("Scroll left")).toBeTruthy();
    expect(screen.getByTitle("Scroll right")).toBeTruthy();

    act(() => size(strip, { client: 300, scroll: 900, left: 600 }));
    expect(screen.getByTitle("Scroll left")).toBeTruthy();
    expect(screen.queryByTitle("Scroll right")).toBeNull();
  });

  it("pages by most of the visible width and keeps arrows out of the tab order", () => {
    render(<Strip />);
    const strip = screen.getByTestId("strip");
    const scrollBy = vi.fn();
    strip.scrollBy = scrollBy as unknown as typeof strip.scrollBy;
    act(() => size(strip, { client: 300, scroll: 900 }));
    const next = screen.getByTitle("Scroll right");
    expect(next.tabIndex).toBe(-1);
    fireEvent.click(next);
    expect(scrollBy).toHaveBeenCalledWith(expect.objectContaining({ left: 240 }));
  });

  it("turns a vertical mouse wheel into sideways scrolling until an end", () => {
    render(<Strip />);
    const strip = screen.getByTestId("strip");
    act(() => size(strip, { client: 300, scroll: 900 }));

    const down = new WheelEvent("wheel", { deltaY: 100, bubbles: true, cancelable: true });
    strip.dispatchEvent(down);
    expect(down.defaultPrevented).toBe(true);
    expect(strip.scrollLeft).toBe(100);

    // At the far end the page takes the wheel back.
    strip.scrollLeft = 600;
    const past = new WheelEvent("wheel", { deltaY: 100, bubbles: true, cancelable: true });
    strip.dispatchEvent(past);
    expect(past.defaultPrevented).toBe(false);

    // A trackpad's own sideways swipe is left alone.
    strip.scrollLeft = 200;
    const sideways = new WheelEvent("wheel", { deltaX: 80, deltaY: 10, bubbles: true, cancelable: true });
    strip.dispatchEvent(sideways);
    expect(sideways.defaultPrevented).toBe(false);
  });
});

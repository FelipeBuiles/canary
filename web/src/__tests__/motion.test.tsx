import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { Stamp, useArrival } from "../components/ui/motion";
import { WholeBookReveal } from "../components/pages/WholeBookReveal";
import { editionKeyFor } from "../lib/editionKey";

function Arrival({ flag }: { flag: boolean }) {
  const { arrived, settle } = useArrival(flag);
  return <Stamp play={arrived} onSettled={settle}>Printed</Stamp>;
}

// jsdom has no AnimationEvent, so React listens for the prefixed name.
function endAnimation(element: HTMLElement) {
  act(() => {
    element.dispatchEvent(new Event("webkitAnimationEnd", { bubbles: true }));
  });
}

beforeEach(() => { vi.useFakeTimers(); window.localStorage.clear(); });
afterEach(() => { vi.useRealTimers(); });

describe("print-physics motion", () => {
  it("rests without motion when the work was already done, and stamps only a new arrival", () => {
    const view = render(<Arrival flag />);
    act(() => { vi.runAllTimers(); });
    expect(screen.getByText("Printed").className).not.toContain("animate-stamp-slam");

    view.rerender(<Arrival flag={false} />);
    view.rerender(<Arrival flag />);
    act(() => { vi.runAllTimers(); });
    const stamp = screen.getByText("Printed");
    expect(stamp.className).toContain("animate-stamp-slam");
    endAnimation(stamp);
    expect(stamp.className).not.toContain("animate-stamp-slam");
  });

  it("pulls back into the whole book once per edition", () => {
    const key = editionKeyFor("book", [{ page_number: 1, revision: 1 }, { page_number: 2, revision: 1 }]);
    const reveal = (ready: boolean, editionKey = key) => (
      <I18nProvider><WholeBookReveal ready={ready} editionKey={editionKey}><p>pages</p></WholeBookReveal></I18nProvider>
    );
    const view = render(reveal(false));
    act(() => { vi.runAllTimers(); });
    const gallery = screen.getByTestId("whole-book-gallery");
    expect(gallery.className).not.toContain("animate-whole-book");

    view.rerender(reveal(true));
    act(() => { vi.runAllTimers(); });
    expect(gallery.className).toContain("animate-whole-book");
    endAnimation(gallery);
    expect(gallery.className).not.toContain("animate-whole-book");

    view.unmount();
    render(reveal(true));
    act(() => { vi.runAllTimers(); });
    expect(screen.getByTestId("whole-book-gallery").className).not.toContain("animate-whole-book");
    expect(editionKeyFor("book", [{ page_number: 1, revision: 2 }, { page_number: 2, revision: 1 }])).not.toBe(key);
  });
});

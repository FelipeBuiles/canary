import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PageNavigator } from "../components/compose/PageNavigator";
import type { PageSummary } from "../types/api";

const PAGES: PageSummary[] = [
  { page_number: 1, panel_count: 3, layout: "grid" },
  { page_number: 2, panel_count: 5, layout: "grid" },
];

function thumbImg(n: number): HTMLImageElement {
  // The <img alt> is unique per page; the surrounding button's accessible
  // name also concatenates the page number + panel count, so query by alt.
  return screen.getByAltText(`Page ${n} thumbnail`) as HTMLImageElement;
}

describe("PageNavigator thumbnails", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("re-fetches a missing PNG (cache-busting ?t=) while compose is running", () => {
    render(
      <PageNavigator
        project="proj"
        pages={PAGES}
        currentPage={1}
        onSelect={() => {}}
        shouldRetryThumbs
      />,
    );

    // Initial src has no cache-buster.
    expect(thumbImg(1).src).not.toContain("?t=");

    // PNG not ready yet → 404 → start retrying. Wrap in act() so the state
    // update flushes before the timer-driven setTick below.
    act(() => fireEvent.error(thumbImg(1)));

    act(() => vi.advanceTimersByTime(3000));
    expect(thumbImg(1).src).toContain("?t=1");

    act(() => vi.advanceTimersByTime(3000));
    expect(thumbImg(1).src).toContain("?t=2");
  });

  it("stops appending ticks once shouldRetryThumbs is false (compose complete)", () => {
    const { rerender } = render(
      <PageNavigator
        project="proj"
        pages={PAGES}
        currentPage={1}
        onSelect={() => {}}
        shouldRetryThumbs
      />,
    );

    act(() => fireEvent.error(thumbImg(1)));
    act(() => vi.advanceTimersByTime(3000));
    expect(thumbImg(1).src).toContain("?t=1");

    // Stage completes → retry disabled. Further time must not bump the src.
    rerender(
      <PageNavigator
        project="proj"
        pages={PAGES}
        currentPage={1}
        onSelect={() => {}}
        shouldRetryThumbs={false}
      />,
    );
    act(() => vi.advanceTimersByTime(9000));
    expect(thumbImg(1).src).toContain("?t=1");
  });

  it("clears failed state (no further ticks) once the image loads", () => {
    render(
      <PageNavigator
        project="proj"
        pages={PAGES}
        currentPage={1}
        onSelect={() => {}}
        shouldRetryThumbs
      />,
    );

    act(() => fireEvent.error(thumbImg(1)));
    act(() => vi.advanceTimersByTime(3000));
    expect(thumbImg(1).src).toContain("?t=1");

    // PNG arrives on the next attempt → clear failed.
    act(() => fireEvent.load(thumbImg(1)));
    act(() => vi.advanceTimersByTime(9000));
    expect(thumbImg(1).src).toContain("?t=1");
  });

  it("shows the page-number placeholder (always-on background)", () => {
    render(
      <PageNavigator project="proj" pages={PAGES} currentPage={1} onSelect={() => {}} />,
    );
    // The numeric placeholder is rendered behind the <img> regardless of load.
    const btn = thumbImg(1).closest("button")!;
    expect(btn.textContent).toContain("1");
  });

  it("falls back to the live page preview when the rendered PNG is missing", () => {
    render(<PageNavigator project="proj" pages={PAGES} currentPage={1} onSelect={() => {}} />);

    act(() => fireEvent.error(thumbImg(1)));

    expect(screen.getByTitle("Page 1 live preview").getAttribute("src")).toBe(
      "/api/projects/proj/pages/1/preview",
    );
  });

  it("does not retry by default (shouldRetryThumbs omitted)", () => {
    render(<PageNavigator project="proj" pages={PAGES} currentPage={1} onSelect={() => {}} />);
    act(() => fireEvent.error(thumbImg(1)));
    act(() => vi.advanceTimersByTime(9000));
    // No cache-buster appended without explicit opt-in.
    expect(thumbImg(1).src).not.toContain("?t=");
  });
});

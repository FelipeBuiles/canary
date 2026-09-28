import { act, fireEvent, render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { useLiveStageAsset } from "../hooks/useLiveStageAsset";

function ProbeHarness({ timestamp, stageRegenerating }: { timestamp: number; stageRegenerating: boolean }) {
  const { probe, hasImage, imageSrc } = useLiveStageAsset("/asset.png", timestamp, stageRegenerating);
  return <div data-testid="probe" data-available={hasImage} data-src={imageSrc}>{probe}</div>;
}

function getProbe(container: HTMLElement) {
  const image = container.querySelector("img");
  expect(image).not.toBeNull();
  return image!;
}

describe("useLiveStageAsset", () => {
  it("does not refetch when the parent status poll timestamp changes", () => {
    const view = render(<ProbeHarness timestamp={100} stageRegenerating />);
    const first = getProbe(view.container);
    const firstSrc = first.getAttribute("src");

    view.rerender(<ProbeHarness timestamp={200} stageRegenerating />);

    const current = getProbe(view.container);
    expect(current).toBe(first);
    expect(current.getAttribute("src")).toBe(firstSrc);
  });

  it("retries a missing asset on a timer instead of on every render", () => {
    vi.useFakeTimers();
    try {
      const view = render(<ProbeHarness timestamp={100} stageRegenerating />);
      const first = getProbe(view.container);
      const firstSrc = first.getAttribute("src");

      fireEvent.error(first);
      view.rerender(<ProbeHarness timestamp={200} stageRegenerating />);
      expect(getProbe(view.container).getAttribute("src")).toBe(firstSrc);

      act(() => vi.advanceTimersByTime(4_999));
      expect(getProbe(view.container).getAttribute("src")).toBe(firstSrc);

      act(() => vi.advanceTimersByTime(1));
      expect(getProbe(view.container).getAttribute("src")).not.toBe(firstSrc);
    } finally {
      vi.useRealTimers();
    }
  });

  it("invalidates a successful probe when the image revision changes", () => {
    const view = render(<ProbeHarness timestamp={100} stageRegenerating />);
    fireEvent.load(getProbe(view.container));
    expect(view.getByTestId("probe").dataset.available).toBe("true");

    view.rerender(<ProbeHarness timestamp={200} stageRegenerating />);
    expect(view.getByTestId("probe").dataset.available).toBe("false");
    expect(getProbe(view.container).getAttribute("src")).toBe("/asset.png?t=200");

    view.rerender(<ProbeHarness timestamp={300} stageRegenerating={false} />);
    expect(view.container.querySelector("img")).toBeNull();
    expect(view.getByTestId("probe").dataset.src).toBe("/asset.png?t=300");
  });

  it("stops probing after the asset loads", () => {
    const view = render(<ProbeHarness timestamp={100} stageRegenerating />);
    fireEvent.load(getProbe(view.container));

    expect(view.container.querySelector("img")).toBeNull();
  });
});

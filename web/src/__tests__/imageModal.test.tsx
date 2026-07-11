import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImageModal } from "../components/ui/ImageModal";

afterEach(() => {
  document.body.style.overflow = "";
  vi.restoreAllMocks();
});

describe("ImageModal", () => {
  it("keeps its scroll lock and key listener stable across parent rerenders", () => {
    const addListener = vi.spyOn(window, "addEventListener");
    const removeListener = vi.spyOn(window, "removeEventListener");
    const firstClose = vi.fn();
    const latestClose = vi.fn();
    const { rerender } = render(
      <ImageModal isOpen onClose={firstClose} src="/plate.png" alt="Location plate" />,
    );

    expect(document.body.style.overflow).toBe("hidden");
    expect(addListener.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(1);

    rerender(
      <ImageModal isOpen onClose={latestClose} src="/plate.png" alt="Location plate" />,
    );

    expect(removeListener.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(0);
    expect(addListener.mock.calls.filter(([type]) => type === "keydown")).toHaveLength(1);

    window.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(firstClose).not.toHaveBeenCalled();
    expect(latestClose).toHaveBeenCalledOnce();
  });
});

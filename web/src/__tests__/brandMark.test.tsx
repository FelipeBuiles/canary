import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BrandMark } from "../components/BrandMark";

describe("BrandMark", () => {
  it("uses the reduction-safe micro master for decorative marks by default", () => {
    const { container } = render(<BrandMark className="test-mark" />);
    const mark = container.querySelector("img");

    expect(mark?.getAttribute("src")).toBe(
      "/brand/scenewright-panel-frame/scenewright-symbol-micro.svg",
    );
    expect(mark?.getAttribute("alt")).toBe("");
    expect(mark?.getAttribute("aria-hidden")).toBe("true");
  });

  it("can expose an accessible name and select a full symbol treatment", () => {
    render(<BrandMark title="Scenewright" variant="reversed" />);
    const mark = screen.getByRole("img", { name: "Scenewright" });

    expect(mark.getAttribute("src")).toBe(
      "/brand/scenewright-panel-frame/scenewright-symbol-reversed.svg",
    );
    expect(mark.hasAttribute("aria-hidden")).toBe(false);
  });
});

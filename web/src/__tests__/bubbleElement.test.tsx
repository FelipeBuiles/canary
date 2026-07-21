import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BubbleElement } from "../components/compose/BubbleElement";
import type { Bubble } from "../types/api";

const pinnedThought: Bubble = {
  id: "thought",
  type: "thought",
  text: "Keep me inside the panel.",
  speaker_id: null,
  speaker_name: null,
  side: "left",
  full_width: false,
  x: -120,
  y: -40,
  width: null,
  tail_x: null,
  tail_y: null,
  tail_direction: "auto",
  font_family: null,
  font_size: null,
  font_color: null,
  fill_color: null,
  border_color: null,
  border_width: null,
};

describe("BubbleElement", () => {
  it("clamps legacy negative pinned coordinates inside the panel", () => {
    render(<BubbleElement bubble={pinnedThought} selected={false} />);

    const bubble = screen.getByRole("button", { name: /thought bubble/i });
    expect(bubble.style.left).toBe("8px");
    expect(bubble.style.top).toBe("8px");
  });

  it("renders an inside-bubble tail target above the tail SVG so it remains draggable", () => {
    const bubble = {
      ...pinnedThought,
      type: "speech" as const,
      x: 20,
      y: 20,
      tail_x: 40,
      tail_y: 40,
    };

    const { container } = render(
      <div className="panel">
        <BubbleElement bubble={bubble} selected />
      </div>,
    );

    const handle = container.querySelector("[data-tail-handle]");
    const tailSvg = container.querySelector(".speaker-tail");
    expect(handle).not.toBeNull();
    expect(tailSvg).not.toBeNull();
    expect(tailSvg?.contains(handle)).toBe(false);
  });
});

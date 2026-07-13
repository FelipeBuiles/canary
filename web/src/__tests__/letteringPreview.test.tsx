import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { LetteringPreview } from "../components/compose/LetteringPreview";

describe("LetteringPreview", () => {
  it("positions every lettering element inside the sample panel", () => {
    const { container } = render(<LetteringPreview lettering={undefined} />);

    expect((screen.getByText("A quiet street, just past midnight.").closest(".caption") as HTMLElement).style.top).toBe("28px");
    expect((screen.getByText("Who's there?").closest(".bubble") as HTMLElement).style.top).toBe("225px");
    expect((screen.getByText("…something is wrong.").closest(".bubble") as HTMLElement).style.top).toBe("350px");
    expect(screen.getByText("KRAK!").style.bottom).toBe("28px");
    expect(container.querySelectorAll(".letter-shape")).toHaveLength(3);
    expect(container.querySelector(".auto-tail")).not.toBeNull();
  });
});

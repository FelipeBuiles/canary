import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ConfirmDrawer } from "../components/composites/ConfirmDrawer";
import { RerunDrawer } from "../components/composites/RerunDrawer";

describe("bottom drawer placement", () => {
  it("portals confirmation drawers to the viewport layer", () => {
    const { container } = render(
      <ConfirmDrawer
        open
        title="Page 9"
        body="Draw one complete page."
        onConfirm={() => undefined}
        onClose={() => undefined}
      />,
    );

    const dialog = screen.getByRole("alertdialog", { name: "Page 9" });
    const overlay = dialog.parentElement;

    expect(container.contains(dialog)).toBe(false);
    expect(overlay?.parentElement).toBe(document.body);
    expect(overlay?.className).toContain("fixed inset-0");
    expect(overlay?.className).toContain("items-end");
  });

  it("portals rerun drawers to the same viewport layer", () => {
    const { container } = render(
      <RerunDrawer
        open
        stageName="Pages"
        impactStages={[]}
        onConfirm={() => undefined}
        onClose={() => undefined}
      />,
    );

    const dialog = screen.getByRole("alertdialog", { name: "Rerun Pages?" });
    const overlay = dialog.parentElement;

    expect(container.contains(dialog)).toBe(false);
    expect(overlay?.parentElement).toBe(document.body);
    expect(overlay?.className).toContain("fixed inset-0");
    expect(overlay?.className).toContain("items-end");
  });
});

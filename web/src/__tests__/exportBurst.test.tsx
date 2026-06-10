import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ExportBurst } from "../components/compose/ExportBurst";

describe("ExportBurst", () => {
  it("shows the ceremony with page count and download link", () => {
    render(
      <ExportBurst
        pageCount={24}
        format="pdf"
        downloadUrl="/api/projects/demo/export/pdf"
        onDismiss={() => undefined}
      />,
    );

    expect(screen.getByText("HOT OFF THE PRESS")).toBeTruthy();
    expect(screen.getByText("ISSUE READY — 24 PAGES")).toBeTruthy();
    const link = screen.getByRole("link", { name: /DOWNLOAD PDF/ });
    expect(link.getAttribute("href")).toBe("/api/projects/demo/export/pdf");
    expect(link.hasAttribute("download")).toBe(true);
  });

  it("uses singular PAGE for a one-page issue", () => {
    render(
      <ExportBurst
        pageCount={1}
        format="cbz"
        downloadUrl="/api/projects/demo/export/cbz"
        onDismiss={() => undefined}
      />,
    );

    expect(screen.getByText("ISSUE READY — 1 PAGE")).toBeTruthy();
    expect(screen.getByRole("link", { name: /DOWNLOAD CBZ/ })).toBeTruthy();
  });

  it("dismisses on Escape, the ESC button, and click-outside — but not on panel clicks", async () => {
    const user = userEvent.setup();
    const onDismiss = vi.fn();

    render(
      <ExportBurst
        pageCount={8}
        format="pdf"
        downloadUrl="/api/projects/demo/export/pdf"
        onDismiss={onDismiss}
      />,
    );

    await user.click(screen.getByText("HOT OFF THE PRESS"));
    expect(onDismiss).not.toHaveBeenCalled();

    await user.keyboard("{Escape}");
    expect(onDismiss).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(onDismiss).toHaveBeenCalledTimes(2);

    await user.click(screen.getByRole("presentation"));
    expect(onDismiss).toHaveBeenCalledTimes(3);
  });
});

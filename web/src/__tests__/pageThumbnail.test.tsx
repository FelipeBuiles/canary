import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PageThumbnail } from "../components/pages/PageThumbnail";
import { I18nProvider } from "../i18n";

describe("PageThumbnail", () => {
  it("keeps the parent review action accessible after failure and retries a new revision", () => {
    const review = vi.fn();
    const onRevealEnd = vi.fn();
    const preview = (src: string) => (
      <I18nProvider>
        <button aria-label="Open page 1, revision 2" onClick={review}>
          <PageThumbnail src={src} alt="Complete page thumbnail 1" reveal={false} onRevealEnd={onRevealEnd} />
        </button>
      </I18nProvider>
    );
    const view = render(preview("/page-1-r2.png"));

    fireEvent.error(screen.getByRole("img", { name: "Complete page thumbnail 1" }));

    expect(screen.queryByRole("img")).toBeNull();
    expect(screen.getByText("Preview unavailable")).toBeTruthy();
    expect(screen.getByText("Open the page to inspect its saved artwork.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Open page 1, revision 2" }));
    expect(review).toHaveBeenCalledOnce();

    view.rerender(preview("/page-1-r3.png"));
    expect(screen.getByRole("img", { name: "Complete page thumbnail 1" }).getAttribute("src")).toBe("/page-1-r3.png");
    expect(screen.queryByText("Preview unavailable")).toBeNull();
  });
});

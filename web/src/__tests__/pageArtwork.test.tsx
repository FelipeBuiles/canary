import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { I18nProvider } from "../i18n";
import { PageArtwork } from "../components/pages/PageArtwork";

const artwork = (src: string) => (
  <I18nProvider><PageArtwork src={src} alt="Page 1 artwork" /></I18nProvider>
);

describe("PageArtwork", () => {
  it("reserves a loading surface and reveals artwork only after the image loads", () => {
    const { container } = render(artwork("/page-1-r1.png"));
    const image = screen.getByAltText("Page 1 artwork");

    expect(screen.getByRole("status").textContent).toBe("Loading artwork…");
    expect(container.firstElementChild?.getAttribute("aria-busy")).toBe("true");
    expect(image.classList.contains("invisible")).toBe(true);
    // The old unsized image border caused the brief vertical line.
    expect(image.className).not.toMatch(/\bborder(?:-|\b)/);

    fireEvent.load(image);

    expect(screen.queryByRole("status")).toBeNull();
    expect(container.firstElementChild?.getAttribute("aria-busy")).toBe("false");
    expect(image.classList.contains("invisible")).toBe(false);
  });

  it("offers a real retry after failure and returns to the loading state", () => {
    render(artwork("/page-1-r1.png"));
    const failedImage = screen.getByAltText("Page 1 artwork");
    fireEvent.error(failedImage);

    expect(screen.getByRole("alert").textContent).toBe("The page image could not be loaded.");
    expect(screen.queryByAltText("Page 1 artwork")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    const retriedImage = screen.getByAltText("Page 1 artwork");
    expect(retriedImage).not.toBe(failedImage);
    expect(retriedImage.getAttribute("src")).toBe("/page-1-r1.png");
    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toBeTruthy();
    fireEvent.load(retriedImage);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("loads a new revision independently of the previous image state", () => {
    const view = render(artwork("/page-1-r1.png"));
    fireEvent.load(screen.getByAltText("Page 1 artwork"));
    view.rerender(artwork("/page-1-r2.png"));

    expect(screen.getByRole("status")).toBeTruthy();
    const newImage = screen.getByAltText("Page 1 artwork");
    expect(newImage.getAttribute("src")).toBe("/page-1-r2.png");
    expect(newImage.classList.contains("invisible")).toBe(true);
    fireEvent.error(newImage);
    view.rerender(artwork("/page-1-r3.png"));

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.getByRole("status")).toBeTruthy();
    expect(screen.getByAltText("Page 1 artwork").getAttribute("src")).toBe("/page-1-r3.png");
    fireEvent.load(screen.getByAltText("Page 1 artwork"));
    expect(screen.queryByRole("status")).toBeNull();
  });
});

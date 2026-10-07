import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImageGenerationPreview } from "../components/composites/ImageGenerationPreview";
import { usePipelineStore } from "../store/pipeline";

vi.mock("../i18n", () => ({ useI18n: () => ({ t: (value: string) => value }) }));

const first = "data:image/webp;base64,first";
const second = "data:image/webp;base64,second";

function updatePreview(src: string, index: number, request = "one") {
  act(() => usePipelineStore.setState({ projectId: "book~part-1", imagePreviews: {
    "page:1": { request_id: request, image_url: src, preview_index: index },
  } }));
}

const animationEnd = (element: Element) => fireEvent(element, new Event(
  // JSDOM lacks AnimationEvent, so React registers the prefixed event.
  "AnimationEvent" in window ? "animationend" : "webkitAnimationEnd", { bubbles: true },
));

function decode(container: HTMLElement, src: string) {
  fireEvent.load(Array.from(container.querySelectorAll("img")).find((image) => image.getAttribute("src") === src && image.classList.contains("opacity-0"))!);
}

const card = (active = true, finalSrc: string | null = "/final.png") => <ImageGenerationPreview
  project="book~part-1" target="page:1" active={active} finalSrc={finalSrc ?? undefined} aspect="2 / 3" label="DRAWING PAGE…">
  <span>Saved artwork or failure</span>
</ImageGenerationPreview>;

afterEach(() => {
  cleanup();
  usePipelineStore.setState({ projectId: null, imagePreviews: {} });
});

describe("ImageGenerationPreview", () => {
  it("keeps decoded pixels visible until each sharper preview and the final image load", async () => {
    updatePreview(first, 0);
    const view = render(card());
    decode(view.container, first);
    expect(screen.getByRole("img", { name: "DRAWING PAGE…" }).style.getPropertyValue("--preview-blur")).toBe("12px");
    updatePreview(second, 1);
    expect(screen.getByRole("img", { name: "DRAWING PAGE…" }).getAttribute("src")).toBe(first);
    decode(view.container, second);
    expect(screen.getByRole("img", { name: "DRAWING PAGE…" }).style.getPropertyValue("--preview-blur")).toBe("6px");
    view.rerender(card(false));
    expect(view.container.querySelector(".image-focus-layer")?.getAttribute("src")).toBe(second);
    decode(view.container, "/final.png");
    expect((view.container.querySelector(".image-focus-layer") as HTMLElement).style.getPropertyValue("--preview-blur")).toBe("0px");
    animationEnd(view.container.querySelector(".image-focus-layer")!);
    // The handoff holds until the card's own image could be painted, then fades.
    expect(view.container.querySelector(".image-focus-layer")).toBeTruthy();
    await waitFor(() => expect(view.container.querySelector(".image-preview-release")).toBeTruthy());
    animationEnd(view.container.querySelector(".image-preview-release")!);
    expect(view.container.querySelector(".image-focus-layer")).toBeNull();
    expect(screen.getByText("Saved artwork or failure")).toBeTruthy();
  });

  it("clears an abandoned preview on fallback or a failure without saved artwork", () => {
    updatePreview(first, 0);
    const view = render(card());
    decode(view.container, first);
    act(() => usePipelineStore.setState({ imagePreviews: {} }));
    expect(view.container.querySelector(".image-focus-layer")).toBeNull();
    view.rerender(card(false, null));
    expect(screen.getByText("Saved artwork or failure")).toBeTruthy();
    expect(view.container.querySelector(".image-focus-layer")).toBeNull();
  });

  it("does not display another part's preview", () => {
    updatePreview(first, 0);
    const view = render(<ImageGenerationPreview project="book~part-2" target="page:1" active aspect="2 / 3" />);
    expect(view.container.querySelector('img[src^="data:"]')).toBeNull();
  });

  it("sharpens completed pixels even when they match the preceding preview", () => {
    updatePreview(first, 2);
    const view = render(card());
    decode(view.container, first);
    updatePreview(first, 3);
    decode(view.container, first);
    expect(screen.getByRole("img", { name: "DRAWING PAGE…" }).style.getPropertyValue("--preview-blur")).toBe("0px");
  });

  it("leaves ordinary saved cards to their existing lazy image loader", () => {
    const view = render(card(false));
    expect(view.container.querySelector("img.opacity-0")).toBeNull();
  });

  it("keeps existing artwork during a redraw until the first preview arrives", () => {
    const view = render(<ImageGenerationPreview project="book~part-1" target="page:1" active keepChildren aspect="2 / 3" label="DRAWING PAGE…">
      <button type="button">Open saved page</button>
    </ImageGenerationPreview>);
    expect(screen.getByRole("button", { name: "Open saved page" })).toBeTruthy();
    expect(screen.queryByLabelText("DRAWING PAGE…")).toBeNull();
    updatePreview(first, 0);
    decode(view.container, first);
    expect(screen.getByRole("img", { name: "DRAWING PAGE…" })).toBeTruthy();
    // The preview overlay never swallows clicks meant for the card beneath.
    expect(view.container.querySelector(".image-focus-layer")!.parentElement!.className).toContain("pointer-events-none");
  });

  it("presses drafts over the placeholder, then settles completed and saved pixels", () => {
    updatePreview(first, 0);
    const view = render(card());
    decode(view.container, first);
    const layer = () => view.container.querySelector(".image-focus-layer")!;
    expect(layer().classList.contains("image-focus-develop")).toBe(true);
    expect(view.container.querySelector(".image-press-bar")).toBeTruthy();
    const placeholderCount = () => view.container.querySelectorAll("canvas").length;
    expect(placeholderCount()).toBe(1);
    animationEnd(layer());
    expect(placeholderCount()).toBe(0);
    updatePreview(second, 3);
    decode(view.container, second);
    expect(layer().classList.contains("image-focus-resolve")).toBe(true);
    expect(view.container.querySelector(".image-press-bar")).toBeNull();
    view.rerender(card(false));
    decode(view.container, "/final.png");
    expect(layer().classList.contains("image-focus-handoff")).toBe(true);
  });

  it("bridges a finished job to its saved file without falling back to the placeholder", async () => {
    updatePreview(first, 3, "done");
    const view = render(card(true, null));
    decode(view.container, first);
    animationEnd(view.container.querySelector(".image-focus-layer")!);
    // The job reports completion before the card learns it is idle.
    act(() => usePipelineStore.setState((state) => ({ imagePreviews: {
      "page:1": { ...state.imagePreviews["page:1"], settled: true } } })));
    expect(view.container.querySelectorAll("canvas")).toHaveLength(0);
    expect(view.container.querySelector(".image-focus-layer")?.getAttribute("src")).toBe(first);
    expect(screen.queryByRole("status")).toBeNull();
    // Idle, but the saved file's URL has not arrived yet: still no placeholder or pop.
    view.rerender(card(false, null));
    expect(view.container.querySelector(".image-focus-layer")?.getAttribute("src")).toBe(first);
    view.rerender(card(false));
    decode(view.container, "/final.png");
    animationEnd(view.container.querySelector(".image-focus-layer")!);
    await waitFor(() => expect(view.container.querySelector(".image-preview-release")).toBeTruthy());
    animationEnd(view.container.querySelector(".image-preview-release")!);
    expect(view.container.querySelector(".image-focus-layer")).toBeNull();
    expect(usePipelineStore.getState().imagePreviews["page:1"]).toBeUndefined();
  });

  it("waits for the card's own image to finish fading in before letting go", async () => {
    updatePreview(first, 3);
    const view = render(<ImageGenerationPreview project="book~part-1" target="page:1" active finalSrc="/final.png" aspect="2 / 3">
      <img src="/final.png" alt="saved" style={{ opacity: 0 }} />
    </ImageGenerationPreview>);
    decode(view.container, first);
    view.rerender(<ImageGenerationPreview project="book~part-1" target="page:1" active={false} finalSrc="/final.png" aspect="2 / 3">
      <img src="/final.png" alt="saved" style={{ opacity: 0 }} />
    </ImageGenerationPreview>);
    decode(view.container, "/final.png");
    animationEnd(view.container.querySelector(".image-focus-layer")!);
    const saved = screen.getByAltText("saved") as HTMLImageElement;
    Object.defineProperty(saved, "complete", { value: true });
    Object.defineProperty(saved, "naturalWidth", { value: 800 });
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 200)); });
    expect(view.container.querySelector(".image-preview-release")).toBeNull();
    saved.style.opacity = "1";
    await waitFor(() => expect(view.container.querySelector(".image-preview-release")).toBeTruthy());
  });

  it("ignores finished pixels left from a generation this card did not watch", () => {
    act(() => usePipelineStore.setState({ projectId: "book~part-1", imagePreviews: {
      "page:1": { request_id: "old", image_url: first, preview_index: 3, settled: true },
    } }));
    const view = render(card(true, null));
    expect(view.container.querySelector('img[src^="data:"]')).toBeNull();
  });
});

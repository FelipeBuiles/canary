import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { HomePage } from "../pages/HomePage";
import { SHOWCASE_SHELF } from "../lib/showcaseShelf";

const storageValues = new Map<string, string>();
const storage: Storage = {
  get length() {
    return storageValues.size;
  },
  clear: () => storageValues.clear(),
  getItem: (key) => storageValues.get(key) ?? null,
  key: (index) => Array.from(storageValues.keys())[index] ?? null,
  removeItem: (key) => storageValues.delete(key),
  setItem: (key, value) => storageValues.set(key, value),
};

function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
  }));
}

function renderHomePage() {
  return render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><MemoryRouter>
      <I18nProvider>
        <HomePage />
      </I18nProvider>
    </MemoryRouter></QueryClientProvider>,
  );
}

describe("Scenewright homepage", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });
  beforeEach(() => {
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      value: storage,
    });
    storage.clear();
  });


  it("leads with the product outcome and a real signup path", () => {
    renderHomePage();

    expect(screen.getByRole("heading", { level: 1, name: "Turn your novel into a comic" })).toBeTruthy();
    const start = screen.getAllByRole("link", { name: /Start your comic/ });
    expect(start.length).toBeGreaterThanOrEqual(3);
    for (const link of start) expect(link.getAttribute("href")).toBe("/signup");
    expect(screen.getByRole("link", { name: /Read a finished book/ }).getAttribute("href")).toBe("#books");
    expect(screen.getByText(/EPUB, PDF or TXT in/)).toBeTruthy();
    expect(screen.queryByText(/500 free credits/i)).toBeNull();
    expect(document.body.textContent).not.toMatch(/landing\./);
  });

  it("puts every showcase book on the shelf as a link to its reader", () => {
    renderHomePage();

    const shelf = screen.getByRole("region", { name: "Read a book made with Scenewright" });
    const books = within(shelf).getAllByRole("listitem");
    expect(books).toHaveLength(SHOWCASE_SHELF.length);
    const monkey = within(shelf).getByRole("link", { name: /The Monkey's Paw.*W\. W\. Jacobs.*20 pages/ });
    expect(monkey.getAttribute("href")).toBe("/read/b32d070d85f942278577140e7f55778b");
    expect(within(shelf).getByRole("link", { name: /Browse the sample stories/ }).getAttribute("href")).toBe("/samples");
    expect(within(shelf).getByText(/Not customer work; results vary/)).toBeTruthy();
  });

  it("matches the shelf to the showcase manifests", () => {
    const root = resolve(__dirname, "../../../showcase/books");
    const manifests = readdirSync(root).filter(name => existsSync(join(root, name, "book.json"))).sort()
      .map(name => JSON.parse(readFileSync(join(root, name, "book.json"), "utf8")) as { id: string; title: string; author: string; pages: unknown[] });
    expect(SHOWCASE_SHELF.map(({ id, author, pages }) => ({ id, author, pages })))
      .toEqual(manifests.map(({ id, author, pages }) => ({ id, author, pages: pages.length })));
    for (const book of SHOWCASE_SHELF) expect(existsSync(resolve(__dirname, `../../public${book.cover}`))).toBe(true);
  });

  it("walks through the five stations and marks the four approvals", () => {
    renderHomePage();

    const steps = within(screen.getByRole("region", { name: "From manuscript to finished book" })).getAllByRole("listitem")
      .filter(item => item.classList.contains("home-step"));
    expect(steps.map(step => within(step).getByRole("heading", { level: 3 }).textContent))
      .toEqual(["Approve the brief", "Choose the look", "Meet the cast", "Review every page", "Export and share"]);
    expect(steps.filter(step => step.textContent?.includes("You approve"))).toHaveLength(4);
  });

  it("links rights language to the public terms and states the copyright caveat", () => {
    renderHomePage();

    const rightsLink = screen.getByRole("link", { name: /Read the full rights and copyright terms/ });
    expect(rightsLink.getAttribute("href")).toBe("/legal/terms");
    expect(screen.getByText(/Purely generated imagery may have limited copyright protection/)).toBeTruthy();
    expect(screen.getByRole("link", { name: /See pricing/ }).getAttribute("href")).toBe("/pricing");
  });

  it("lets public visitors switch the marketing page to Spanish and French", async () => {
    renderHomePage();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "ES" })); });
    expect(await screen.findByRole("heading", { level: 1, name: "Convierte tu novela en un cómic" })).toBeTruthy();
    expect(document.documentElement.lang).toBe("es");
    expect(screen.getByRole("region", { name: "Lee un libro hecho con Scenewright" })).toBeTruthy();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "FR" })); });
    expect(await screen.findByRole("heading", { level: 1, name: "Transformez votre roman en BD" })).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /Commencer votre BD/ })[0].getAttribute("href")).toBe("/signup");
    expect(screen.getByRole("link", { name: "Aller au contenu" })).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/landing\./);
  });

  it("shows the film as a poster and loads the privacy-enhanced player only on play", () => {
    const { container } = renderHomePage();
    expect(screen.getByRole("heading", { name: "Your novel. Any style." })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Styles" }).getAttribute("href")).toBe("#styles");
    expect(container.querySelector(".home-film iframe")).toBeNull();
    expect(screen.getByRole("link", { name: /Watch on YouTube/ }).getAttribute("href")).toBe("https://www.youtube.com/watch?v=W-1bPTQXQaQ");

    fireEvent.click(screen.getByRole("button", { name: /Play the Scenewright film/ }));

    const player = screen.getByTitle(/Scenewright: your novel in any style/);
    expect(player.getAttribute("src")).toMatch(/^https:\/\/www\.youtube-nocookie\.com\/embed\/W-1bPTQXQaQ\?autoplay=1&rel=0/);
    expect(screen.queryByRole("button", { name: /Play the Scenewright film/ })).toBeNull();
  });

  it("plays a muted, silent hero loop that can be paused", () => {
    stubReducedMotion(false);
    vi.spyOn(HTMLMediaElement.prototype, "play").mockResolvedValue(undefined);
    const pause = vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(() => undefined);
    const { container } = renderHomePage();

    const video = container.querySelector(".home-hero video") as HTMLVideoElement;
    // The poster can paint without competing with a multi-megabyte video.
    expect(video.getAttribute("src")).toBeNull();
    expect(video.getAttribute("poster")).toBe("/marketing/masque-flipbook-poster.webp");
    expect(video.muted).toBe(true);
    expect(video.loop).toBe(true);
    expect(video.autoplay).toBe(true);
    expect(screen.getByRole("figure", { name: /Looping video: one scene from The Masque of the Red Death/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(video.getAttribute("src")).toBe("/marketing/masque-flipbook.mp4");

    Object.defineProperty(video, "paused", { configurable: true, value: false });
    fireEvent.playing(video);
    fireEvent.click(screen.getByRole("button", { name: "Pause" }));
    expect(pause).toHaveBeenCalledOnce();
    fireEvent.pause(video);
    expect(screen.getByRole("button", { name: "Play" }).getAttribute("aria-pressed")).toBe("true");
  });

  it("offers Play when autoplay is blocked and reflects actual playback events", async () => {
    stubReducedMotion(false);
    const play = vi.spyOn(HTMLMediaElement.prototype, "play")
      .mockRejectedValueOnce(new DOMException("Autoplay blocked", "NotAllowedError"))
      .mockResolvedValue(undefined);
    const { container } = renderHomePage();
    const video = container.querySelector("video")!;

    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: "Play" }));
      await play.mock.results[0].value.catch(() => undefined);
    });
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Play" }));
    expect(play).toHaveBeenCalledTimes(2);
    fireEvent.playing(video);
    expect(screen.getByRole("button", { name: "Pause" })).toBeTruthy();
    fireEvent.pause(video);
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
    fireEvent.playing(video);
    fireEvent.error(video);
    expect(screen.getByRole("button", { name: "Play" })).toBeTruthy();
  });

  it("shows only the poster when the visitor prefers reduced motion", () => {
    stubReducedMotion(true);
    const { container } = renderHomePage();

    expect(container.querySelector("video")).toBeNull();
    expect(container.querySelector(".home-hero .home-sheet img")?.getAttribute("src")).toBe("/marketing/masque-flipbook-poster.webp");
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("compares three real editions of one story with their license", () => {
    renderHomePage();

    const styles = screen.getByRole("region", { name: "Your novel. Any style." });
    const links = within(styles).getAllByRole("link", { name: /at full size/ }).map((link) => link.getAttribute("href"));
    expect(links).toEqual([
      "/marketing/janitor-riso-page-01.webp",
      "/marketing/janitor-gouache-page-01.webp",
      "/marketing/janitor-oil-page-01.webp",
    ]);
    expect(within(styles).getByText(/JanitorCakeworth, SCP Wiki, CC BY-SA 3.0/)).toBeTruthy();
    expect(within(styles).getByText(/Not customer work; results vary/)).toBeTruthy();
  });

  it("keeps credits and costs out of the showcase media", () => {
    renderHomePage();

    for (const name of ["Read a book made with Scenewright", "Your novel. Any style.", "From manuscript to finished book"]) {
      expect(screen.getByRole("region", { name }).textContent).not.toMatch(/\bcredits?\b|\bcosts?\b|\bfree\b|US\$/i);
    }
    expect(document.querySelector(".home-hero__visual")?.textContent).not.toMatch(/credit|cost|free/i);
  });
});

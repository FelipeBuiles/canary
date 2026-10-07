import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { HomePage } from "../pages/HomePage";

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


  it("places finished books immediately after the scene sample", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [{
        id: "sample", title: "A complete story", author: "An author", description: "A finished edition.",
        pages: [{ number: 1, url: "/page.jpg", width: 120, height: 180 }],
      }],
    }));
    renderHomePage();
    const heading = await screen.findByRole("heading", { name: "Read a finished book" });
    const section = heading.closest("section");
    expect(section?.previousElementSibling?.id).toBe("continuity");
    expect(section?.nextElementSibling?.classList.contains("landing-story-shelf")).toBe(true);
    expect(section?.nextElementSibling?.nextElementSibling?.id).toBe("process");
    expect(screen.getByRole("link", { name: /Explore all stories/ }).getAttribute("href")).toBe("/samples");
    expect(screen.getByRole("link", { name: "Read book" }).getAttribute("href")).toBe("/read/sample");
  });

  it("leads with the product outcome and a real signup path", () => {
    renderHomePage();

    expect(
      screen.getByRole("heading", {
        level: 1,
        name: "Your story. Its first comic scene.",
      }),
    ).toBeTruthy();

    const sampleLink = screen.getAllByRole("link", { name: /Create my first scene/ })[0];
    expect(sampleLink.getAttribute("href")).toBe("/signup");
    expect(screen.getByText(/AI-assisted visual adaptation/)).toBeTruthy();
    expect(screen.queryByText(/500 free credits/i)).toBeNull();
  });

  it("shows licensed source stories separately from finished comic books", async () => {
    vi.stubGlobal("fetch", vi.fn().mockImplementation(async (url: string) => ({
      ok: true,
      json: async () => String(url).endsWith("/projects/short-stories") ? [{
        code: "kaitlin-out-of-space", title: "Kaitlin Out of Space", author: "Krishan Coupland",
        words: 3117, genres: ["sci-fi"], description: "An older woman welcomes a visitor.",
      }] : [],
    })));
    renderHomePage();
    expect(await screen.findByRole("heading", { name: "Kaitlin Out of Space" })).toBeTruthy();
    expect(screen.getByRole("link", { name: /Read and choose/ }).getAttribute("href")).toBe("/samples?story=kaitlin-out-of-space");
    expect(screen.queryByRole("heading", { name: "Read a finished book" })).toBeNull();
  });

  it("makes provisional development pages readable without claiming customer or production proof", () => {
    renderHomePage();

    expect(screen.getByText(/H. P. Lovecraft, page 40 .* Not customer work; results vary/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Read a development sample" }).getAttribute("href")).toBe("#continuity");
    expect(screen.getAllByRole("link", { name: "Read page 40 at full size" })[0].getAttribute("href")).toBe("/marketing/cthulhu-page-40.webp");
    expect(screen.getByText(/Automated checks do not guarantee visual quality/)).toBeTruthy();
    expect(screen.getByText(/not a fixed number of pages/)).toBeTruthy();
  });

  it("localizes the new entry point and sample links in French", async () => {
    renderHomePage();
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "FR" })); });

    expect(await screen.findByRole("heading", { level: 1, name: "Votre récit. Sa première scène de BD." })).toBeTruthy();
    expect(screen.getAllByRole("link", { name: /Créer ma première scène/ })[0].getAttribute("href")).toBe("/signup");
    expect(screen.getAllByRole("link", { name: "Lire la page 12 en taille réelle" })[0].getAttribute("href")).toBe("/marketing/elm-and-keep-page-12.webp");
    expect(screen.getByRole("link", { name: "Aller au contenu" })).toBeTruthy();
  });

  it("links rights language to the public terms and states the copyright caveat", () => {
    renderHomePage();

    const rightsLink = screen.getByRole("link", {
      name: /Read the full rights and copyright terms/,
    });
    expect(rightsLink.getAttribute("href")).toBe("/legal/terms");
    expect(screen.getByText(/Purely generated imagery may have limited copyright protection/)).toBeTruthy();
  });

  it("lets public visitors switch the marketing page to Spanish", async () => {
    renderHomePage();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "ES" })); });

    expect(
      await screen.findByRole("heading", {
        level: 1,
        name: "Tu historia. Su primera escena de cómic.",
      }),
    ).toBeTruthy();
    expect(document.documentElement.lang).toBe("es");
  });

  it("sells custom styles in the Look step", () => {
    renderHomePage();

    expect(screen.getByRole("heading", { level: 3, name: "Describe it, show it, or ask for six" })).toBeTruthy();
    expect(screen.getByText(/let Scenewright pitch six directions made for your story/)).toBeTruthy();
    expect(screen.queryByText(/Pick a visual direction/)).toBeNull();
  });

  it("shows the film as a poster and loads the privacy-enhanced player only on play", () => {
    const { container } = renderHomePage();
    expect(screen.getByRole("heading", { name: "See a story become a comic." })).toBeTruthy();
    expect(screen.getByRole("link", { name: "Watch" }).getAttribute("href")).toBe("#film");
    expect(container.querySelector(".landing-film iframe")).toBeNull();
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

    const video = container.querySelector(".landing-hero video") as HTMLVideoElement;
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
    const toggle = screen.getByRole("button", { name: "Pause" });
    fireEvent.click(toggle);
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
    expect(container.querySelector(".landing-hero img")?.getAttribute("src")).toBe("/marketing/masque-flipbook-poster.webp");
    expect(screen.queryByRole("button", { name: "Pause" })).toBeNull();
  });

  it("compares three real editions of one story with their license", () => {
    renderHomePage();

    const strip = screen.getByRole("region", { name: "One story, three books." });
    const links = within(strip).getAllByRole("link", { name: /at full size/ }).map((link) => link.getAttribute("href"));
    expect(new Set(links)).toEqual(new Set([
      "/marketing/janitor-riso-page-01.webp",
      "/marketing/janitor-gouache-page-01.webp",
      "/marketing/janitor-oil-page-01.webp",
    ]));
    expect(within(strip).getByText(/JanitorCakeworth, SCP Wiki, CC BY-SA 3.0/)).toBeTruthy();
    expect(within(strip).getByText(/Not customer work; results vary/)).toBeTruthy();
    expect(strip.closest("section#continuity")).toBeTruthy();
  });

  it("links a sample story to the showcase book it became", () => {
    renderHomePage();

    const sample = screen.getByRole("region", { name: "Read the story. Then read the book it became." });
    expect(within(sample).getByRole("link", { name: /Read the original story/ }).getAttribute("href")).toBe("/samples?story=kaitlin-out-of-space");
    expect(within(sample).getAllByRole("img")).toHaveLength(3);
    expect(within(sample).getByText(/Krishan Coupland \(CC0\)/)).toBeTruthy();
  });

  it("keeps credits and costs out of the showcase media", () => {
    renderHomePage();

    for (const name of ["One story, three books.", "Read the story. Then read the book it became."]) {
      expect(screen.getByRole("region", { name }).textContent).not.toMatch(/credit|cost|free|US\$/i);
    }
    expect(document.querySelector(".landing-hero__visual")?.textContent).not.toMatch(/credit|cost|free/i);
  });

  it("localizes the new showcase blocks in Spanish and French", async () => {
    renderHomePage();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "ES" })); });
    expect(await screen.findByRole("heading", { level: 3, name: "Descríbelo, muéstralo o pide seis" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Una historia, tres libros." })).toBeTruthy();

    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "FR" })); });
    expect(await screen.findByRole("heading", { level: 3, name: "Décrivez-le, montrez-le ou demandez-en six" })).toBeTruthy();
    expect(screen.getByRole("region", { name: "Lisez la nouvelle. Puis lisez le livre qu’elle est devenue." })).toBeTruthy();
  });
});

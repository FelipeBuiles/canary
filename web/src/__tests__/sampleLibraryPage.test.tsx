import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";

const readStory = vi.hoisted(() => vi.fn().mockResolvedValue({
  code: "an-education",
  text: "AN EDUCATION\nBy Angie\n\nA student enters the classroom.\n\nThe teacher has a surprise.",
}));
vi.mock("../api/projects", () => ({ readShortStory: readStory }));
vi.mock("../api/queries", () => ({
  useShortStories: () => ({
    data: [
      { code: "an-education", title: "An Education", author: "Angie", words: 955,
        genres: ["fantasy"], description: "A student meets a teacher.", license: "CC0 1.0", source_kind: "curated" },
      { code: "the-cats-of-ulthar", title: "The Cats of Ulthar", author: "H. P. Lovecraft", words: 1341,
        genres: ["gothic", "horror"], publish_year: 1920, source_kind: "archive",
        rights_note: "Rights for classic archive stories vary by work and jurisdiction. Check the original publication and your local rights before publishing an adaptation." },
    ],
    isLoading: false, isError: false, isFetching: false, refetch: vi.fn(),
  }),
}));

import { SampleLibraryPage } from "../pages/SampleLibraryPage";

function LocationProbe() {
  const location = useLocation();
  return <output aria-label="Current route">{location.pathname}{location.search}</output>;
}

describe("public sample shelf", () => {
  it("opens a deep-linked story, returns to discovery, and carries the choice to signup", async () => {
    const user = userEvent.setup();
    render(<I18nProvider><MemoryRouter initialEntries={["/samples?story=an-education"]}>
      <Routes>
        <Route path="/samples" element={<SampleLibraryPage />} />
        <Route path="/signup" element={<p>Signup destination</p>} />
      </Routes>
      <LocationProbe />
    </MemoryRouter></I18nProvider>);

    expect(await screen.findByText("A student enters the classroom.")).toBeTruthy();
    expect(document.title).toBe("An Education by Angie — Scenewright");
    expect(document.querySelector('link[rel="canonical"]')?.getAttribute("href")).toBe("https://scenewright.ink/samples?story=an-education");
    await user.click(screen.getByRole("button", { name: /Back to stories/ }));
    expect(document.title).toBe("Sample stories — Scenewright");
    expect(screen.getByLabelText("Current route").textContent).toBe("/samples");
    await user.click(screen.getAllByRole("button", { name: "READ STORY" })[0]);
    expect(screen.getByLabelText("Current route").textContent).toBe("/samples?story=an-education");
    await user.click(screen.getByRole("link", { name: /START WITH THIS STORY/ }));
    expect(screen.getByLabelText("Current route").textContent).toBe("/signup?sample=an-education");
  });

  it("finds classic Lovecraft stories without leaving the main search", async () => {
    const user = userEvent.setup();
    readStory.mockResolvedValueOnce({ code: "the-cats-of-ulthar", text: "It is said that in Ulthar, no man may kill a cat." });
    render(<I18nProvider><MemoryRouter initialEntries={["/samples"]}>
      <Routes><Route path="/samples" element={<SampleLibraryPage />} /></Routes>
    </MemoryRouter></I18nProvider>);
    await user.type(screen.getByRole("searchbox", { name: "Search stories" }), "lovecraft");
    expect(screen.getByRole("heading", { name: "The Cats of Ulthar" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "An Education" })).toBeNull();
    expect(screen.getByText("Rights vary by location")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "READ STORY" }));
    expect(await screen.findByText("It is said that in Ulthar, no man may kill a cat.")).toBeTruthy();
    expect(screen.getByText(/Rights for classic archive stories vary/)).toBeTruthy();
  });
});

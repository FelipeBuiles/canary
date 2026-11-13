import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ColdOpen } from "../components/story/ColdOpen";
import type { ColdOpen as ColdOpenData, ColdOpenLook } from "../api/styles";
import { I18nProvider } from "../i18n";

const state = vi.hoisted(() => ({ coldOpen: null as ColdOpenData | null, watching: [] as boolean[] }));
const favorite = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));
vi.mock("../api/queries", () => ({
  useColdOpen: (_project: string, watching: boolean) => {
    state.watching.push(watching);
    return { data: { cold_open: state.coldOpen } };
  },
  useSetColdOpenFavorite: () => favorite,
}));
const offer = vi.hoisted(() => ({ available: false }));
vi.mock("../api/cardGrant", () => ({
  useAccountOffer: () => ({ data: { free_opening: { status: "used" }, first_purchase_bonus_percent: 0,
    card_grant: { enabled: true, available: offer.available, claimed: false, credits: 1200 } } }),
}));

function look(id: string, label: string, status: ColdOpenLook["status"]): ColdOpenLook {
  return {
    id, label, medium: `${label} medium`, status, error: null, adopted: false,
    image_url: status === "ready" ? `/api/projects/p/cold-open/proof/${id}?v=1` : null,
    preview_target: `cold_open/proof_${id}.png`,
  };
}

function coldOpen(overrides: Partial<ColdOpenData> = {}): ColdOpenData {
  return {
    status: "ready", phase: null, scene_title: "A Game of Chess", chapter: 1, story_copy: true,
    scene_summary: "Herbert declares checkmate as the gate bangs.", favorite_look_id: null,
    looks: [look("noir", "Rain-Slick Noir", "ready"), look("ink", "Bold Ink", "ready"), look("lino", "Linocut", "failed")],
    ...overrides,
  };
}

function view(props: Partial<Parameters<typeof ColdOpen>[0]> = {}) {
  return render(<MemoryRouter><I18nProvider><ColdOpen project="owner:p" variant="press" {...props} /></I18nProvider></MemoryRouter>);
}

beforeEach(() => {
  state.coldOpen = null;
  state.watching = [];
  favorite.mutate.mockReset();
  offer.available = false;
  localStorage.clear();
});

describe("ColdOpen", () => {
  it("stays out of the way until Extract has read the opening", () => {
    const { container } = view({ watching: true });
    expect(container.textContent).toBe("");
    expect(state.watching).toContain(true);
  });

  it("shows the press while the first page prints, with no credits", () => {
    state.coldOpen = coldOpen({ status: "printing", phase: "printing",
      looks: [look("noir", "Rain-Slick Noir", "printing"), look("ink", "Bold Ink", "queued"), look("lino", "Linocut", "queued")] });
    const { container } = view();
    expect(screen.getByRole("heading", { name: "Your first page is on the press" })).toBeTruthy();
    expect(screen.getByText("Chapter 1 · A Game of Chess")).toBeTruthy();
    expect(screen.getByText("On the house")).toBeTruthy();
    expect(screen.getByText("Linocut")).toBeTruthy();
    expect(container.textContent).not.toMatch(/credit/i);
    expect(screen.queryByRole("button", { name: "This one" })).toBeNull();
  });

  it("lets the author pick a printed page as a preference, and toggle it off", async () => {
    const user = userEvent.setup();
    state.coldOpen = coldOpen();
    const { rerender } = view({ variant: "look" });
    // Only the press explains a dropped page; in Look it is simply absent.
    expect(screen.queryByText("This one didn't make it off the press.")).toBeNull();
    expect(screen.getAllByRole("button", { name: "This one" })).toHaveLength(2);
    await user.click(screen.getAllByRole("button", { name: "This one" })[1]);
    expect(favorite.mutate).toHaveBeenCalledWith({ project: "owner:p", lookId: "ink" });

    state.coldOpen = coldOpen({ favorite_look_id: "ink" });
    rerender(<MemoryRouter><I18nProvider><ColdOpen project="owner:p" variant="look" /></I18nProvider></MemoryRouter>);
    await user.click(screen.getByRole("button", { name: "Your pick" }));
    expect(favorite.mutate).toHaveBeenLastCalledWith({ project: "owner:p", lookId: null });
  });

  it("beside the Brief, stays a quiet card that keeps the Brief the task", () => {
    state.coldOpen = coldOpen({ favorite_look_id: "ink" });
    view({ variant: "rail", lookReady: true });
    expect(screen.queryByRole("heading", { name: "Your story, three ways" })).toBeNull();
    expect(screen.queryByRole("button", { name: "This one" })).toBeNull();
    expect(screen.getByText("Your pick: Bold Ink")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: /Look closer at/ })).toHaveLength(2);
    expect(screen.getByRole("link", { name: "Make the whole book look like this" }).getAttribute("href"))
      .toBe("/project/owner:p/styles");
  });

  it("counts pages still on the press beside the Brief", () => {
    state.coldOpen = coldOpen({ status: "printing", phase: "printing",
      looks: [look("noir", "Rain-Slick Noir", "ready"), look("ink", "Bold Ink", "printing"), look("lino", "Linocut", "queued")] });
    view({ variant: "rail", lookReady: true });
    expect(screen.getByText("On the press: 1 of 3 printed")).toBeTruthy();
  });

  it("is absent from Look and the Brief when nothing was printed", () => {
    state.coldOpen = coldOpen({ status: "failed", looks: [look("noir", "Rain-Slick Noir", "failed")] });
    expect(view({ variant: "rail" }).container.textContent).toBe("");
    expect(view({ variant: "look" }).container.textContent).toBe("");
  });

  it("says plainly when nothing was printed", () => {
    state.coldOpen = coldOpen({ status: "failed", looks: [look("noir", "Rain-Slick Noir", "failed")] });
    view();
    expect(screen.getByRole("heading", { name: "The press jammed on your first pages" })).toBeTruthy();
    expect(screen.getByText(/Nothing was charged/)).toBeTruthy();
  });

  it("points printed pages to the first-chapter credits only where the account can claim them", () => {
    state.coldOpen = coldOpen();
    const { unmount } = view();
    expect(screen.queryByRole("link", { name: /verify a card/ })).toBeNull();
    unmount();
    offer.available = true;
    view();
    const link = screen.getByRole("link", { name: /verify a card for 1,200 credits for a first chapter/ });
    expect(link.getAttribute("href")).toBe("/credits");
  });
});

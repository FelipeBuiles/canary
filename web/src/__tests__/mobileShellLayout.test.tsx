import fs from "node:fs";
import path from "node:path";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { setMedia } from "mock-match-media";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { BottomBarPortal, TopBarSlotProvider } from "../layout/TopBarSlot";
import { RoomHeader } from "../components/composites/RoomHeader";
import { DESKTOP_LAYOUT_QUERY } from "../hooks/useDesktopLayout";

vi.mock("../api/queries", () => ({
  useCreditBalance: () => ({ data: { balance_credits: 500 } }),
}));

vi.mock("../hooks/useAuth", () => ({
  useAuth: () => ({ user: { email: "reader@example.com" } }),
}));

vi.mock("../layout/SideNav", () => ({ SideNav: () => null }));
vi.mock("../components/ui/FloatingIndicator", () => ({ FloatingIndicator: () => null }));
vi.mock("../components/InsufficientCreditsDialog", () => ({
  InsufficientCreditsDialog: () => null,
}));

import { AppTopBar } from "../layout/AppTopBar";
import { Shell } from "../layout/Shell";

describe("mobile project shell", () => {
  it("compresses the desktop room masthead on mobile project routes", () => {
    const { getByRole } = render(
      <MemoryRouter initialEntries={["/project/demo/pages"]}>
        <I18nProvider>
          <TopBarSlotProvider>
            <AppTopBar />
          </TopBarSlotProvider>
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(getByRole("banner").className).toContain("h-14");
    expect(getByRole("banner").className).toContain("studio-desktop:h-shell-top");
  });

  it("tracks the visible mobile viewport for the content scroll area", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/project/demo/pages"]}>
        <I18nProvider>
          <Shell />
        </I18nProvider>
      </MemoryRouter>,
    );

    const shell = container.firstElementChild as HTMLElement;
    expect(shell.className).toContain("h-dvh");
    expect(shell.className).not.toContain("h-screen");
  });

  function renderRoom(onContinue = vi.fn()) {
    return render(
      <MemoryRouter initialEntries={["/project/demo/pages"]}>
        <I18nProvider>
          <Routes>
            <Route path="/project/:id" element={<Shell />}>
              <Route path="pages" element={<>
                <RoomHeader kicker="PAGES" title="REVIEW COMPLETE PAGES" />
                <p>Artwork to review</p>
                <BottomBarPortal><footer><button onClick={onContinue}>Continue</button></footer></BottomBarPortal>
              </>} />
            </Route>
          </Routes>
        </I18nProvider>
      </MemoryRouter>,
    );
  }

  it.each([{ width: 390, height: 640 }, { width: 844, height: 390 }, { width: 768, height: 1024 }, { width: 1023, height: 1200 }])("keeps room titles and approval actions in the content flow at $width × $height", (size) => {
    setMedia(size);
    renderRoom();
    const main = screen.getByRole("main");
    expect(main.contains(screen.getByRole("heading", { name: "REVIEW COMPLETE PAGES" }))).toBe(true);
    expect(main.contains(screen.getByRole("button", { name: "Continue" }))).toBe(true);
  });

  it("preserves desktop slots and moves working actions when the viewport changes", () => {
    setMedia({ width: 1366, height: 768 });
    const onContinue = vi.fn();
    renderRoom(onContinue);
    const main = screen.getByRole("main");
    expect(screen.getByRole("banner").contains(screen.getByRole("heading", { name: "REVIEW COMPLETE PAGES" }))).toBe(true);
    expect(main.contains(screen.getByRole("button", { name: "Continue" }))).toBe(false);

    act(() => setMedia({ width: 390, height: 640 }));
    expect(main.contains(screen.getByRole("heading", { name: "REVIEW COMPLETE PAGES" }))).toBe(true);
    expect(main.contains(screen.getByRole("button", { name: "Continue" }))).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onContinue).toHaveBeenCalledOnce();

    act(() => setMedia({ width: 1366, height: 768 }));
    expect(main.contains(screen.getByRole("button", { name: "Continue" }))).toBe(false);
  });

  it("keeps the CSS studio-desktop variant and the JS layout query in agreement", () => {
    const css = fs.readFileSync(path.resolve(import.meta.dirname, "../index.css"), "utf8");
    const variant = /@custom-variant studio-desktop \{\s*@media ([^{]+)\{/.exec(css)?.[1].trim();
    expect(variant).toBe("(width >= 64rem)");
    expect(DESKTOP_LAYOUT_QUERY).toBe("(min-width: 1024px)");
  });
});

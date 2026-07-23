import { render } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { I18nProvider } from "../i18n";
import { TopBarSlotProvider } from "../layout/TopBarSlot";

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
      <MemoryRouter initialEntries={["/project/demo/draw"]}>
        <I18nProvider>
          <TopBarSlotProvider>
            <AppTopBar />
          </TopBarSlotProvider>
        </I18nProvider>
      </MemoryRouter>,
    );

    expect(getByRole("banner").className).toContain("h-14");
    expect(getByRole("banner").className).toContain("md:h-shell-top");
  });

  it("tracks the visible mobile viewport so the approval footer stays on screen", () => {
    const { container } = render(
      <MemoryRouter initialEntries={["/project/demo/draw"]}>
        <I18nProvider>
          <Shell />
        </I18nProvider>
      </MemoryRouter>,
    );

    const shell = container.firstElementChild as HTMLElement;
    expect(shell.className).toContain("h-dvh");
    expect(shell.className).not.toContain("h-screen");
  });
});

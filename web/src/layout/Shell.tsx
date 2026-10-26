import { Outlet, useLocation } from "react-router-dom";
import { SideNav } from "./SideNav";
import { AppTopBar } from "./AppTopBar";
import { TopBarSlotProvider, BottomBarHost } from "./TopBarSlot";
import { FloatingIndicator } from "../components/ui/FloatingIndicator";
import { InsufficientCreditsDialog } from "../components/InsufficientCreditsDialog";
import { useI18n } from "../i18n";

export function Shell() {
  const location = useLocation();
  const isLibrary = location.pathname === "/";
  const showDesktopProjectNav = location.pathname.startsWith("/project/");
  const { t } = useI18n();

  return (
    <TopBarSlotProvider>
      <div className="flex h-dvh flex-col bg-surface-container studio-desktop:flex-row">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:bg-hero-red focus:px-4 focus:py-2 focus:text-bristol focus:font-meta focus:text-[0.6rem] focus:tracking-[0.18em] focus:outline-none"
        >
          {t("SKIP TO CONTENT")}
        </a>
        <SideNav showDesktop={showDesktopProjectNav} />
        <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">
          <AppTopBar />
          <main id="main-content" className="app-workbench min-h-0 min-w-0 flex-1 overflow-y-auto bg-pulp-paper">
            <div className={[
              "app-workbench-sheet flex min-h-full w-full flex-col bg-pulp-paper px-4 pb-4 pt-5 sm:px-6 sm:pb-6 sm:pt-6 studio-desktop:px-5 studio-desktop:py-5 xl:px-6 xl:py-6",
              !isLibrary ? "mx-auto max-w-[1560px]" : "",
              // A room that draws edge to edge drops the sheet's margins.
              "has-[[data-bleed]]:h-full has-[[data-bleed]]:max-w-none has-[[data-bleed]]:p-0!",
            ].join(" ")}>
              <Outlet />
            </div>
          </main>
          <BottomBarHost />
        </div>
        <FloatingIndicator />
        <InsufficientCreditsDialog />
      </div>
    </TopBarSlotProvider>
  );
}

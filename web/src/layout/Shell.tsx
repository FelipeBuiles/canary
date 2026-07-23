import { Outlet, useLocation } from "react-router-dom";
import { SideNav } from "./SideNav";
import { AppTopBar } from "./AppTopBar";
import { TopBarSlotProvider, BottomBarHost } from "./TopBarSlot";
import { FloatingIndicator } from "../components/ui/FloatingIndicator";
import { InsufficientCreditsDialog } from "../components/InsufficientCreditsDialog";
import { cn } from "../lib/cn";
import { useI18n } from "../i18n";

const FULL_HEIGHT_ROUTES = ["/shot-plan", "/adapt", "/direct"];

export function Shell() {
  const location = useLocation();
  const isCompose = location.pathname.endsWith("/compose");
  const isLibrary = location.pathname === "/";
  const showDesktopProjectNav = location.pathname.startsWith("/project/");
  const isFullHeight = FULL_HEIGHT_ROUTES.some((r) => location.pathname.endsWith(r));
  const { t } = useI18n();

  return (
    <TopBarSlotProvider>
      <div className="flex h-dvh flex-col bg-surface-container md:flex-row">
        <a
          href="#main-content"
          className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:bg-hero-red focus:px-4 focus:py-2 focus:text-bristol focus:font-meta focus:text-[0.6rem] focus:tracking-[0.18em] focus:outline-none"
        >
          {t("SKIP TO CONTENT")}
        </a>
        <SideNav showDesktop={showDesktopProjectNav} />
        <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <AppTopBar />
          <main id="main-content" className="app-workbench min-w-0 flex-1 overflow-y-auto bg-pulp-paper">
            <div className={cn(
              "app-workbench-sheet flex w-full flex-col bg-pulp-paper",
              !isCompose && "px-5 py-6 md:px-10 md:py-10",
              isFullHeight || isCompose ? "h-full" : "min-h-full",
              !isCompose && !isLibrary && "mx-auto max-w-[1560px]"
            )}>
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

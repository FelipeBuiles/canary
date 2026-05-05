import { Outlet, useLocation } from "react-router-dom";
import { SideNav } from "./SideNav";
import { AppTopBar } from "./AppTopBar";
import { FloatingIndicator } from "../components/ui/FloatingIndicator";
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
    <div className="flex h-screen flex-col bg-pulp-paper">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:bg-hero-red focus:px-4 focus:py-2 focus:text-bristol focus:font-meta focus:text-[0.6rem] focus:tracking-[0.18em] focus:outline-none"
      >
        {t("SKIP TO CONTENT")}
      </a>
      <AppTopBar />
      <div className="flex flex-1 flex-col overflow-hidden md:flex-row">
        <SideNav showDesktop={showDesktopProjectNav} />
        <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-pulp-paper">
          <div className={cn(
            "flex w-full flex-col px-5 py-6 md:px-10 md:py-10",
            isFullHeight ? "h-full" : "min-h-full",
            !isCompose && !isLibrary && "mx-auto max-w-[1560px]"
          )}>
            <Outlet />
          </div>
        </main>
      </div>
      <FloatingIndicator />
    </div>
  );
}

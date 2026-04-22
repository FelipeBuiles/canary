import { Outlet, useLocation } from "react-router-dom";
import { SideNav } from "./SideNav";
import { FloatingIndicator } from "../components/ui/FloatingIndicator";
import { cn } from "../lib/cn";
import { useI18n } from "../i18n";

export function Shell() {
  const location = useLocation();
  const isCompose = location.pathname.endsWith("/compose");
  const isLibrary = location.pathname === "/";
  const showDesktopProjectNav = location.pathname.startsWith("/project/");
  const { t } = useI18n();

  return (
    <div className="flex h-screen flex-col bg-pulp-paper">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:bg-hero-red focus:px-4 focus:py-2 focus:text-bristol focus:font-meta focus:text-[0.6rem] focus:tracking-[0.18em] focus:outline-none"
      >
        {t("SKIP TO CONTENT")}
      </a>
      <div className="flex flex-1 flex-col overflow-hidden md:flex-row">
        <SideNav showDesktop={showDesktopProjectNav} />
        <main id="main-content" className="min-w-0 flex-1 overflow-y-auto bg-pulp-paper">
          <div className={cn(
            "flex min-h-full w-full flex-col px-5 py-6",
            !isCompose && (isLibrary ? "mx-auto max-w-[1500px]" : "mx-auto max-w-[1318px]")
          )}>
            <Outlet />
          </div>
        </main>
      </div>
      <FloatingIndicator />
    </div>
  );
}

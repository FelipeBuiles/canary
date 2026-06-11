import { useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { useProjectStatus, useProjects } from "../api/queries";
import { InspectDrawer } from "../components/InspectDrawer";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";
import {
  STATIONS,
  getStationState,
  getSubstepState,
  stationForRoute,
  type DrawerKind,
  type Station,
  type StationState,
} from "../lib/stations";

interface SideNavProps {
  showDesktop?: boolean;
}

const STATE_TAG: Record<StationState, { label: string; className: string }> = {
  done: { label: "✓ DONE", className: "text-archive-sage" },
  review: { label: "● REVIEW", className: "text-hero-red" },
  running: { label: "RUNNING", className: "text-narrator-gold animate-pulse" },
  failed: { label: "! FAILED", className: "text-hero-red" },
  wait: { label: "WAIT", className: "text-bristol/28" },
};

export function SideNav({ showDesktop = true }: SideNavProps) {
  const { id: projectId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const { data: status } = useProjectStatus(projectId);
  const { data: projects } = useProjects();
  const [drawer, setDrawer] = useState<DrawerKind | null>(null);

  const current = projects?.find((p) => p.id === projectId);
  const projectTitle = current?.project_name ?? projectId ?? t("PROJECT INDEX");
  const settingsPath = projectId ? `/project/${encodeURIComponent(projectId)}/settings` : "/account";
  const isSettingsActive = location.pathname.endsWith("/settings");

  const activeRoute = location.pathname.split("/").pop() ?? "";
  const activeStation = stationForRoute(activeRoute);

  function goTo(route: string) {
    if (!projectId) return;
    navigate(`/project/${encodeURIComponent(projectId)}/${route}`);
  }

  function renderStationRow(station: Station) {
    const state = getStationState(station, status);
    const tag = STATE_TAG[state];
    const isActive = activeStation?.key === station.key;

    return (
      <div key={station.key} className={cn(isActive && "border-y border-bristol/12 bg-bristol/6")}>
        <button
          type="button"
          onClick={() => goTo(station.primaryRoute)}
          aria-label={`Station ${station.number} ${station.label}: ${tag.label}`}
          aria-current={isActive ? "true" : undefined}
          className={cn(
            "flex w-full items-baseline gap-3 border-l-[3px] px-5 py-3 text-left transition-colors xl:px-6 2xl:py-4",
            isActive ? "border-hero-red" : "border-transparent hover:bg-bristol/5",
          )}
        >
          <span className="font-meta text-[0.56rem] tracking-[0.14em] text-bristol/35">{station.number}</span>
          <span className={cn(
            "font-display text-[1.02rem] font-black uppercase leading-none tracking-[-0.02em] 2xl:text-[1.15rem]",
            isActive ? "text-bristol" : "text-bristol/72",
          )}>
            {t(station.label)}
          </span>
          <span className={cn("ml-auto font-meta text-[0.5rem] leading-none tracking-[0.12em]", tag.className)}>
            {tag.label}
          </span>
        </button>

        {/* Substeps — only the current station expands. */}
        {isActive && (
          <ul className="pb-2 pl-[3px]">
            {station.substeps.map((substep) => {
              const subState = getSubstepState(substep, status);
              const isSubActive = substep.route === activeRoute;
              return (
                <li key={substep.key}>
                  <button
                    type="button"
                    onClick={() =>
                      substep.kind === "auto" && substep.drawer
                        ? setDrawer(substep.drawer)
                        : substep.route && goTo(substep.route)
                    }
                    className={cn(
                      "flex w-full items-center gap-2.5 px-6 py-1.5 text-left font-meta text-[0.56rem] tracking-[0.14em] transition-colors xl:px-7",
                      isSubActive ? "text-bristol" : "text-bristol/48 hover:text-bristol/80",
                    )}
                  >
                    <span
                      aria-hidden
                      className={cn(
                        "h-[7px] w-[7px] shrink-0",
                        subState === "done" && "bg-archive-sage",
                        subState === "current" && "bg-hero-red",
                        subState === "pending" && "border border-bristol/30",
                      )}
                    />
                    <span className="uppercase">{t(substep.label)}</span>
                    {substep.kind === "auto" && (
                      <span className="ml-auto border border-bristol/25 px-1.5 py-0.5 font-meta text-[0.44rem] tracking-[0.12em] text-bristol/45">
                        {t("AUTO · VIEW")}
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }

  const mobileNav = (
    <header className="flex shrink-0 items-center gap-2 border-b-[2px] border-ink-black bg-ink-black px-3 py-2 text-bristol md:hidden">
      <Link to="/" className="flex min-w-0 flex-1 items-center gap-2">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center bg-pulp-paper font-display text-[0.72rem] font-black text-ink-black">
          {projectTitle.charAt(0)}
        </span>
        <span className="min-w-0">
          <span className="block truncate font-display text-[0.88rem] font-bold uppercase leading-none tracking-[-0.02em]">
            {projectTitle}
          </span>
          <span className="mt-1 block font-meta text-[0.48rem] tracking-[0.16em] text-bristol/45">
            ← {t("LIBRARY")}
          </span>
        </span>
      </Link>
      {projectId && (
        <select
          aria-label={t("STATION")}
          value={activeStation?.primaryRoute ?? STATIONS[0].primaryRoute}
          onChange={(event) => goTo(event.target.value)}
          className="max-w-[9.5rem] border border-bristol/20 bg-ink-black px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] text-bristol"
        >
          {STATIONS.map((station) => (
            <option key={station.key} value={station.primaryRoute}>
              {station.number} {t(station.label)}
            </option>
          ))}
        </select>
      )}
    </header>
  );

  if (!showDesktop) return <>{mobileNav}</>;

  return (
    <>
      {mobileNav}
      <aside className="hidden h-full w-[240px] shrink-0 flex-col bg-ink-black text-bristol md:flex xl:w-[270px] 2xl:w-[320px]">
        <Link
          to="/"
          className="flex items-center gap-4 border-b border-bristol/10 px-5 py-5 xl:px-6 xl:py-6"
          aria-label={t("LIBRARY")}
        >
          <span className="flex h-12 w-12 shrink-0 items-center justify-center bg-pulp-paper font-display text-[0.92rem] font-black text-ink-black 2xl:h-14 2xl:w-14 2xl:text-[1rem]">
            {projectTitle.charAt(0)}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-display text-[0.98rem] font-black uppercase leading-none tracking-[-0.02em] 2xl:text-[1.12rem]">
              {projectTitle}
            </span>
            <span className="mt-1.5 block font-meta text-[0.56rem] tracking-[0.16em] text-bristol/38 2xl:text-[0.64rem]">
              ← {t("LIBRARY")}
            </span>
          </span>
        </Link>

        <nav aria-label="Stations" className="min-h-0 flex-1 overflow-y-auto py-3">
          {projectId ? (
            STATIONS.map((station) => renderStationRow(station))
          ) : (
            <div className="px-4 py-4 font-meta text-[0.6rem] tracking-[0.14em] text-bristol/35">
              {t("NO PROJECT SELECTED")}
            </div>
          )}
        </nav>

        <div className="border-t border-bristol/10">
          <Link
            to={settingsPath}
            className={cn(
              "flex w-full items-center gap-3 border-l-[3px] px-5 py-3 font-meta text-[0.62rem] tracking-[0.14em] transition-colors xl:px-6 2xl:text-[0.68rem]",
              isSettingsActive
                ? "border-l-narrator-gold bg-bristol/8 text-bristol"
                : "border-transparent text-bristol/45 hover:bg-bristol/5 hover:text-bristol/70",
            )}
          >
            <span className="text-[0.48rem] 2xl:text-[0.52rem]">⊙</span>
            {t("Settings")}
          </Link>
        </div>
      </aside>

      {projectId && (
        <InspectDrawer project={projectId} kind={drawer} onClose={() => setDrawer(null)} />
      )}
    </>
  );
}

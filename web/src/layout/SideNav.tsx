import { useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { Select } from "../components/ui/Select";
import { useProjectStatus, useProjects } from "../api/queries";
import { InspectDrawer } from "../components/InspectDrawer";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";
import {
  STATIONS,
  getSubstepState,
  getStationState,
  stationDestination,
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
  const [detailsOpen, setDetailsOpen] = useState(false);

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
    const inspectItems = station.substeps.filter(
      (substep): substep is typeof substep & { drawer: DrawerKind } =>
        substep.kind === "auto" && Boolean(substep.drawer),
    );
    const decisionItems = station.substeps.filter(
      (substep): substep is typeof substep & { route: string } =>
        substep.kind === "gated" && Boolean(substep.route),
    );

    return (
      <div key={station.key} className={cn(isActive && "border-y border-bristol/12 bg-bristol/6")}>
        <button
          type="button"
          onClick={() => goTo(stationDestination(station, status))}
          aria-label={`Station ${station.number} ${station.label}: ${tag.label}`}
          aria-current={isActive ? "true" : undefined}
          className={cn(
            "flex min-h-12 w-full items-baseline gap-3 px-5 py-3 text-left transition-colors xl:px-6 2xl:py-4",
            isActive ? "bg-bristol/5" : "hover:bg-bristol/5",
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

        {isActive && decisionItems.length > 1 && (
          <ul className="space-y-1 px-5 pb-2 xl:px-6" aria-label={`${station.label} decisions`}>
            {decisionItems.map((substep) => {
              const substepState = getSubstepState(substep, status);
              const isCurrentRoute = activeRoute === substep.route;
              return (
                <li key={substep.key}>
                  <button
                    type="button"
                    onClick={() => goTo(substep.route)}
                    aria-current={isCurrentRoute ? "page" : undefined}
                    className={cn(
                      "flex min-h-11 w-full items-center gap-2 px-3 text-left font-meta text-[0.52rem] uppercase tracking-[0.12em] transition-colors",
                      isCurrentRoute
                        ? "bg-bristol text-ink-black"
                        : "bg-bristol/5 text-bristol/58 hover:bg-bristol/10 hover:text-bristol",
                    )}
                  >
                    <span aria-hidden className={cn(
                      "flex h-4 w-4 shrink-0 items-center justify-center border text-[0.44rem]",
                      isCurrentRoute ? "border-ink-black/20" : "border-bristol/20",
                    )}>
                      {substepState === "done" ? "✓" : substepState === "current" ? "•" : ""}
                    </span>
                    <span>{t(substep.label)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        {isActive && inspectItems.length > 0 && (
          <div className="px-5 pb-3 xl:px-6">
            <button
              type="button"
              aria-expanded={detailsOpen}
              onClick={() => setDetailsOpen((open) => !open)}
              className="flex min-h-11 w-full items-center justify-between font-meta text-[0.52rem] uppercase tracking-[0.14em] text-bristol/48 transition-colors hover:text-bristol/80"
            >
              <span>{t("How this was made")}</span>
              <span aria-hidden>{detailsOpen ? "−" : "+"}</span>
            </button>
            {detailsOpen && (
              <ul className="space-y-1 pb-1">
                {inspectItems.map((substep) => (
                  <li key={substep.key}>
                    <button
                      type="button"
                      onClick={() => setDrawer(substep.drawer)}
                      className="flex min-h-11 w-full items-center gap-2 bg-bristol/5 px-3 text-left font-meta text-[0.52rem] uppercase tracking-[0.12em] text-bristol/58 transition-colors hover:bg-bristol/10 hover:text-bristol"
                    >
                      <span aria-hidden className="h-1.5 w-1.5 bg-bristol/35" />
                      {t(substep.label)}
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    );
  }

  // Only meaningful inside a project — non-project pages keep just the brand bar.
  const activeDecisions = activeStation?.substeps.filter(
    (substep): substep is typeof substep & { route: string } =>
      substep.kind === "gated" && Boolean(substep.route),
  ) ?? [];

  const mobileNav = projectId == null ? null : (
    <>
      <header className="flex h-shell-top shrink-0 items-center gap-2 border-b-[2px] border-ink-black bg-ink-black px-3 text-bristol md:hidden">
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
        <Select
          aria-label={t("STATION")}
          tone="dark"
          size="sm"
          value={isSettingsActive ? "settings" : (activeStation ? stationDestination(activeStation, status) : STATIONS[0].primaryRoute)}
          onValueChange={goTo}
          options={[
            ...STATIONS.map((station) => ({
              value: stationDestination(station, status),
              label: `${station.number} ${t(station.label)}`,
            })),
            { value: "settings", label: `⚙ ${t("Settings")}` },
          ]}
          className="max-w-[9.5rem]"
        />
      </header>
      {!isSettingsActive && activeDecisions.length > 1 && (
        <nav className="flex shrink-0 border-b-[2px] border-ink-black bg-bristol md:hidden" aria-label={`${activeStation?.label} decisions`}>
          {activeDecisions.map((substep) => (
            <button
              key={substep.key}
              type="button"
              onClick={() => goTo(substep.route)}
              aria-current={activeRoute === substep.route ? "page" : undefined}
              className={cn(
                "min-h-11 flex-1 border-r border-ink-black/12 px-3 font-meta text-[0.52rem] uppercase tracking-[0.12em] last:border-r-0",
                activeRoute === substep.route ? "bg-ink-black text-bristol" : "text-ink-black/55",
              )}
            >
              {t(substep.label)}
            </button>
          ))}
        </nav>
      )}
    </>
  );

  if (!showDesktop) return <>{mobileNav}</>;

  return (
    <>
      {mobileNav}
      <aside className="hidden h-full w-[240px] shrink-0 flex-col bg-ink-black text-bristol md:flex xl:w-[270px] 2xl:w-[320px]">
        <Link
          to="/"
          className="flex h-shell-top shrink-0 items-center gap-3 border-b-[2px] border-bristol/10 px-5 xl:px-6"
          aria-label={t("LIBRARY")}
        >
          <span className="flex h-10 w-10 shrink-0 items-center justify-center bg-pulp-paper font-display text-[0.86rem] font-black text-ink-black">
            {projectTitle.charAt(0)}
          </span>
          <span className="min-w-0">
            <span className="line-clamp-2 font-display text-[0.92rem] font-black uppercase leading-[1.08] tracking-[-0.02em] 2xl:text-[1.05rem]" title={projectTitle}>
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

        <div className="h-16 shrink-0 border-t-[2px] border-bristol/10">
          <Link
            to={settingsPath}
            className={cn(
              "flex h-full w-full items-center gap-3 px-5 font-meta text-[0.62rem] tracking-[0.14em] transition-colors xl:px-6 2xl:text-[0.68rem]",
              isSettingsActive
                ? "bg-bristol/8 text-bristol"
                : "text-bristol/45 hover:bg-bristol/5 hover:text-bristol/70",
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

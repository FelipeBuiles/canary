import { useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { StationDrawer } from "./StationDrawer";
import { TopBarPortal } from "./TopBarSlot";
import { useDesktopLayout } from "../hooks/useDesktopLayout";
import { useProjectStatus, useProjects } from "../api/queries";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";
import { safeReplayLabel } from "../lib/replayPrivacy";
import { Icon } from "../components/ui/Icon";
import { canReadDocument, getRoomAccess } from "../lib/stationAccess";
import { projectFileUrl, splitProjectKey } from "../api/projectScope";
import { PartSwitcher } from "../components/parts/PartSwitcher";
import { ArrowLeft, ChevronDown, LockKeyhole } from "lucide-react";
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

interface ProjectCoverThumbProps {
  projectId: string;
  hasCover: boolean;
  compact?: boolean;
}

const STATE_TAG: Record<StationState, { label: string; className: string }> = {
  done: { label: "✓ DONE", className: "text-archive-sage" },
  review: { label: "● REVIEW", className: "text-hero-red" },
  running: { label: "RUNNING", className: "text-narrator-gold" },
  queued: { label: "QUEUED", className: "text-narrator-gold" },
  failed: { label: "! FAILED", className: "text-hero-red" },
  wait: { label: "WAIT", className: "text-bristol/28" },
};

function ProjectCoverThumb({
  projectId,
  hasCover,
  compact = false,
}: ProjectCoverThumbProps) {
  const [coverFailed, setCoverFailed] = useState(false);
  const showCover = hasCover && !coverFailed;

  return (
    <span
      aria-hidden="true"
      className={cn(
        "relative flex shrink-0 items-center justify-center overflow-hidden border-[2px] border-bristol/20 bg-pulp-paper text-ink-black shadow-[3px_3px_0_0_var(--color-hero-red)]",
        compact ? "h-12 w-9" : "h-16 w-12",
      )}
    >
      {showCover ? (
        <img
          src={projectFileUrl(projectId, "cover/cover.png")}
          alt=""
          className="h-full w-full object-cover"
          onError={() => setCoverFailed(true)}
        />
      ) : (
        <>
          <Icon name="draft" size={compact ? 15 : 18} className="text-ink-black/65" />
          <span className={cn(
            "absolute right-0 top-0 bg-narrator-gold [clip-path:polygon(100%_0,100%_100%,0_0)]",
            compact ? "h-2 w-2" : "h-2.5 w-2.5",
          )} />
        </>
      )}
    </span>
  );
}

export function SideNav({ showDesktop = true }: SideNavProps) {
  const { id: projectId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const [mobileOpen, setMobileOpen] = useState(false);
  const desktop = useDesktopLayout();
  const { data: status } = useProjectStatus(projectId);
  const { data: projects } = useProjects();
  const readingParam = new URLSearchParams(location.search).get("reading");

  const current = projects?.find((p) => p.id === splitProjectKey(projectId ?? "").id);
  const projectTitle = current?.project_name ?? projectId ?? t("PROJECT INDEX");
  const settingsPath = projectId ? `/project/${encodeURIComponent(projectId)}/settings` : "/account";
  const isSettingsActive = location.pathname.endsWith("/settings");

  const activeRoute = location.pathname.split("/").pop() ?? "";
  const activeStation = stationForRoute(activeRoute);

  function goTo(route: string) {
    if (!projectId) return;
    setMobileOpen(false);
    navigate(`/project/${encodeURIComponent(projectId)}/${route}`);
  }

  /** Auto substeps open the read-only inspect drawer in the Pages room. The
  Pages room owns the `reading` search param, so the same link works both
  from inside the room (search-only change) and from any other room. */
  function goToReading(kind: DrawerKind) {
    if (!projectId) return;
    setMobileOpen(false);
    navigate({
      pathname: `/project/${encodeURIComponent(projectId)}/pages`,
      search: `?reading=${kind}`,
    });
  }

  function renderStationRow(station: Station) {
    const state = getStationState(station, status);
    const access = getRoomAccess(stationDestination(station, status), status);
    const unavailable = access.state !== "available";
    const tag = unavailable ? { label: t("Locked"), className: "text-bristol/60" } : STATE_TAG[state];
    const isActive = activeStation?.key === station.key;
    const readingItems = station.substeps.filter(
      (substep): substep is typeof substep & { drawer: DrawerKind } =>
        substep.kind === "auto" && Boolean(substep.drawer),
    );
    const decisionItems = station.substeps.filter(
      (substep): substep is typeof substep & { route: string } =>
        substep.kind === "gated" && Boolean(substep.route),
    );

    return (
      <div key={station.key} className={cn("py-1", isActive && "bg-bristol/6")}>
        <button
          type="button"
          onClick={() => goTo(stationDestination(station, status))}
          disabled={unavailable}
          title={access.state === "locked" ? t(access.message) : undefined}
          aria-label={`Station ${station.number} ${station.label}: ${tag.label}`}
          aria-current={isActive ? "true" : undefined}
          className={cn(
            "flex min-h-14 items-center gap-3 px-3 py-2 text-left transition-[background-color,box-shadow,color,transform] duration-180 ease-[cubic-bezier(0.22,1,0.36,1)] disabled:cursor-not-allowed disabled:opacity-70",
            isActive
              ? "mx-3 w-[calc(100%-1.5rem)] bg-bristol text-ink-black shadow-[4px_4px_0_0_var(--color-hero-red)]"
              : "w-full px-5 hover:bg-bristol/6 xl:px-6",
          )}
        >
          <span className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center border-[2px] font-meta text-[0.58rem] font-bold tracking-[0.08em]",
            isActive ? "border-ink-black bg-narrator-gold text-ink-black" : "border-bristol/20 text-bristol/60",
          )}>
            {station.number}
          </span>
          <span data-ph-safe-label={safeReplayLabel(t(station.label))} className={cn(
            "font-display text-[1.02rem] font-black uppercase leading-none tracking-[-0.02em] 2xl:text-[1.15rem]",
            isActive ? "text-ink-black" : "text-bristol/78",
          )}>
            {t(station.label)}
          </span>
          <span className={cn(
            "ml-auto font-meta text-[0.52rem] font-bold leading-none tracking-[0.08em]",
            tag.className,
            isActive && state === "wait" && "text-ink-black/50",
            isActive && (state === "running" || state === "queued") && "text-ink-muted",
          )}>
            {t(tag.label)}
          </span>
        </button>

        {isActive && decisionItems.length > 1 && (
          <ul className="space-y-1 px-3 pb-2" aria-label={`${station.label} decisions`}>
            {decisionItems.map((substep) => {
              const substepState = getSubstepState(substep, status);
              const isCurrentRoute = activeRoute === substep.route;
              return (
                <li key={substep.key}>
                  <button
                    type="button"
                    onClick={() => goTo(substep.route)}
                    disabled={getRoomAccess(substep.route, status).state !== "available"}
                    aria-current={isCurrentRoute ? "page" : undefined}
                    className={cn(
                      "flex min-h-11 w-full items-center gap-2 px-3 text-left font-body text-[0.75rem] font-bold transition-colors",
                      isCurrentRoute
                        ? "bg-bristol text-ink-black"
                        : "bg-bristol/5 text-bristol/70 hover:bg-bristol/10 hover:text-bristol",
                    )}
                  >
                    <span aria-hidden className={cn(
                      "flex h-4 w-4 shrink-0 items-center justify-center border text-[0.44rem]",
                      isCurrentRoute ? "border-ink-black/20" : "border-bristol/20",
                    )}>
                      {substepState === "done" ? "✓" : substepState === "current" ? "•" : ""}
                    </span>
                    <span data-ph-safe-label={safeReplayLabel(t(substep.label))}>{t(substep.label)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}

        {readingItems.length > 0 && (
          <ul className="space-y-1 px-3 pb-3" aria-label={`${station.label} reading`}>
            {readingItems.map((substep) => {
              const locked = getRoomAccess("pages", status).state !== "available" || !canReadDocument(substep.drawer, status);
              const isCurrentReading = activeRoute === "pages"
                && readingParam === substep.drawer;
              return (
                <li key={substep.key}>
                  <button
                    type="button"
                    onClick={() => goToReading(substep.drawer)}
                    disabled={locked}
                    title={locked ? t("Available when this document is ready") : undefined}
                    aria-current={isCurrentReading ? "page" : undefined}
                    className={cn(
                      "flex min-h-11 w-full items-center gap-2 px-3 text-left font-body text-[0.72rem] font-bold transition-colors disabled:cursor-not-allowed disabled:opacity-50",
                      isCurrentReading
                        ? "bg-bristol text-ink-black"
                        : "bg-bristol/5 text-bristol/70 hover:bg-bristol/10 hover:text-bristol",
                    )}
                  >
                    {locked ? <LockKeyhole size={12} aria-hidden="true" className="shrink-0" /> : <span aria-hidden className="h-1.5 w-1.5 shrink-0 bg-bristol/35" />}
                    <span>{t(substep.label)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>
    );
  }

  const currentPart = status?.parts?.find((part) => part.id === splitProjectKey(projectId ?? "").part);
  const activeIndex = activeStation ? STATIONS.findIndex((station) => station.key === activeStation.key) : -1;
  const progress = activeIndex >= 0 ? ((activeIndex + 1) / STATIONS.length) * 100 : 0;
  const closeDrawer = () => setMobileOpen(false);

  /** The pressroom: shared by the desktop sidebar and the compact drawer. */
  function renderPressroom(inDrawer: boolean) {
    const onNavigate = inDrawer ? closeDrawer : undefined;
    return (
      <>
        <Link
          to="/"
          onClick={onNavigate}
          className="flex h-shell-top shrink-0 items-center gap-3 border-b-[2px] border-bristol/10 px-5 xl:px-6"
          aria-label={t("LIBRARY")}
        >
          {projectId && (
            <ProjectCoverThumb
              key={projectId}
              projectId={projectId}
              hasCover={status?.has_cover ?? current?.has_cover ?? false}
            />
          )}
          <span className="min-w-0">
            <span className="line-clamp-2 font-display text-[0.92rem] font-black uppercase leading-[1.08] tracking-[-0.02em] 2xl:text-[1.05rem]" title={projectTitle}>
              {projectTitle}
            </span>
            <span className="mt-1.5 block font-meta text-[0.56rem] font-semibold tracking-[0.1em] text-bristol/65 2xl:text-[0.64rem]">
              ← {t("LIBRARY")}
            </span>
          </span>
        </Link>

        {projectId && status?.parts && status.parts.length > 0 && (
          <div className="shrink-0 border-b-[2px] border-bristol/10 px-5 py-3 xl:px-6">
            <PartSwitcher project={projectId} parts={status.parts} className="w-full" onNavigate={onNavigate} />
          </div>
        )}

        <nav aria-label={inDrawer ? t("STATION") : "Stations"} className="min-h-0 flex-1 overflow-y-auto py-3">
          {projectId ? (
            STATIONS.map((station) => renderStationRow(station))
          ) : (
            <div className="px-4 py-4 font-meta text-[0.6rem] tracking-[0.14em] text-bristol/35">
              {t("NO PROJECT SELECTED")}
            </div>
          )}
        </nav>

        <div className="h-shell-footer shrink-0 border-t-[2px] border-bristol/10">
          <Link
            to={settingsPath}
            onClick={onNavigate}
            aria-current={isSettingsActive ? "page" : undefined}
            className={cn(
              "flex h-full w-full items-center gap-3 px-5 font-meta text-[0.62rem] tracking-[0.14em] transition-colors xl:px-6 2xl:text-[0.68rem]",
              isSettingsActive
                ? "bg-bristol text-ink-black"
                : "text-bristol/70 hover:bg-bristol/8 hover:text-bristol",
            )}
          >
            <Icon name="settings" size={15} />
            {t("Settings")}
          </Link>
        </div>
      </>
    );
  }

  const partLine = currentPart && (status?.parts?.length ?? 0) > 1
    ? t("Part {number} of {count}", { number: currentPart.ordinal, count: status?.parts?.length ?? 0 })
    : null;

  const mobileNav = projectId == null ? null : (
    <>
      <TopBarPortal>
        {/* Compact navigator: the active station token, as the sidebar shows it. */}
        <div className="relative flex min-w-0 flex-1 items-stretch studio-desktop:hidden">
          <Link
            to="/"
            aria-label={t("Back to projects")}
            className="flex w-12 shrink-0 items-center justify-center border-r-[2px] border-ink-black/10 text-ink-black transition-colors hover:bg-surface-container sm:w-14"
          >
            <ArrowLeft size={18} aria-hidden="true" />
          </Link>
          <button
            type="button"
            aria-label={t("STATION")}
            aria-haspopup="dialog"
            aria-expanded={mobileOpen && !desktop}
            onClick={() => setMobileOpen(true)}
            className="group flex min-w-0 flex-1 items-center gap-3 px-3 pb-1 text-left transition-colors hover:bg-surface-container sm:px-4"
          >
            <span aria-hidden="true" className="hidden sm:flex">
              <ProjectCoverThumb key={projectId} projectId={projectId} hasCover={status?.has_cover ?? current?.has_cover ?? false} compact />
            </span>
            <span
              aria-hidden="true"
              className="flex h-8 w-8 shrink-0 items-center justify-center border-[2px] border-ink-black bg-narrator-gold font-meta text-[0.58rem] font-bold tracking-[0.08em] text-ink-black"
            >
              {activeStation ? activeStation.number : <Icon name="settings" size={14} />}
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate font-display text-[1.05rem] font-black uppercase leading-none tracking-[-0.02em] text-ink-black">
                {activeStation ? t(activeStation.label) : t("Settings")}
              </span>
              <span className="mt-1 block truncate font-meta text-[0.6rem] font-semibold tracking-[0.04em] text-ink-muted">
                {projectTitle}{partLine && ` · ${partLine}`}
              </span>
            </span>
            <span aria-hidden="true" className="flex h-8 w-8 shrink-0 items-center justify-center border-[2px] border-ink-black/15 text-ink-black transition-colors group-hover:border-ink-black">
              <ChevronDown size={14} />
            </span>
          </button>
          {activeStation && (
            <span aria-hidden="true" className="absolute inset-x-0 bottom-0 h-[4px] bg-surface-variant">
              <span className="relative block h-full bg-hero-red" style={{ width: `${progress}%` }}>
                <span className="absolute -right-1 bottom-0 h-[4px] w-2 bg-narrator-gold" />
              </span>
            </span>
          )}
        </div>
      </TopBarPortal>
      <StationDrawer open={mobileOpen && !desktop} label={projectTitle} onClose={closeDrawer}>
        {renderPressroom(true)}
      </StationDrawer>
    </>
  );

  if (!showDesktop) return <>{mobileNav}</>;

  return (
    <>
      {mobileNav}
      <aside className="pressroom-sidebar hidden h-full w-[240px] shrink-0 flex-col bg-ink-black text-bristol studio-desktop:flex xl:w-[270px] 2xl:w-[320px]">
        {renderPressroom(false)}
      </aside>
    </>
  );
}

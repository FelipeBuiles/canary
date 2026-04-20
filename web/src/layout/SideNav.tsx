import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation, Link } from "react-router-dom";
import {
  useProjectStatus,
  useApproveStage,
  useProjects,
} from "../api/queries";
import { useRunAction } from "../hooks/useRunAction";
import { STAGE_ORDER } from "../types/api";
import type { StageStatus, ProjectSummary } from "../types/api";
import { Button } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import { useI18n } from "../i18n";

function stageBadgeStyle(status: StageStatus) {
  if (status === "complete") return "bg-archive-sage text-bristol";
  if (status === "running") return "bg-narrator-gold text-ink-black animate-pulse";
  if (status === "awaiting_review") return "bg-hero-red text-bristol";
  if (status === "failed") return "bg-hero-red text-bristol";
  return "bg-pulp-paper text-ink-black/45";
}

type NavRoute = "styles" | "settings";

const NAV_ITEMS: { icon: "styles" | "settings"; label: string; route: NavRoute; projectOnly?: boolean }[] = [
  { icon: "styles", label: "Styles", route: "styles", projectOnly: true },
];

function ProjectSwitcher({
  current,
  projects,
}: {
  current: ProjectSummary | undefined;
  projects: ProjectSummary[] | undefined;
}) {
  const [open, setOpen] = useState(false);
  const navigate = useNavigate();
  const rootRef = useRef<HTMLDivElement>(null);
  const { t } = useI18n();

  useEffect(() => {
    if (!open) return;
    function onClick(e: MouseEvent) {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, [open]);

  const coverUrl = current?.has_cover
    ? `/api/projects/${encodeURIComponent(current.name)}/files/cover/cover.png`
    : null;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="group flex w-full items-start gap-2.5 border-[2px] border-ink-black bg-bristol p-2 text-left hover:bg-pulp-paper"
      >
        <div className="h-11 w-11 shrink-0 overflow-hidden border-[2px] border-ink-black bg-ink-black">
          {coverUrl ? (
            <img src={coverUrl} alt="" className="h-full w-full object-cover" />
          ) : (
            <div className="h-full w-full bg-ink-black" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-display text-[0.82rem] font-bold uppercase leading-[1] tracking-[-0.03em] truncate">
            {current?.project_name ?? t("PROJECT INDEX")}
          </div>
          <div className="mt-1 font-meta text-[0.46rem] tracking-[0.18em] text-ink-black/55">
            NOVEL-TO-INK V1.0
          </div>
        </div>
        <Icon name="chevron-down" size={12} className="mt-1 text-ink-black/55" />
      </button>

      {open && (
        <div className="absolute left-0 right-0 top-[calc(100%+4px)] z-30 border-[2px] border-ink-black bg-bristol shadow-ink-sm">
          <Link
            to="/"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 border-b-[2px] border-ink-black px-3 py-2 font-meta text-[0.58rem] tracking-[0.18em] hover:bg-pulp-paper"
          >
            <Icon name="chevron-left" size={11} />
            {t("LIBRARY")}
          </Link>
          <div className="max-h-[260px] overflow-y-auto">
            {(projects ?? []).map((p) => {
              const isCurrent = p.name === current?.name;
              return (
                <button
                  key={p.name}
                  type="button"
                  onClick={() => {
                    setOpen(false);
                    navigate(`/project/${encodeURIComponent(p.name)}`);
                  }}
                  className={`flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-pulp-paper ${
                    isCurrent ? "bg-pulp-paper" : ""
                  }`}
                >
                  <span className="font-body text-[0.74rem] truncate flex-1">
                    {p.project_name}
                  </span>
                  {isCurrent && <Icon name="check" size={11} className="text-hero-red" />}
                </button>
              );
            })}
          </div>
          <Link
            to="/new"
            onClick={() => setOpen(false)}
            className="flex items-center gap-2 border-t-[2px] border-ink-black px-3 py-2 font-meta text-[0.58rem] tracking-[0.18em] text-hero-red hover:bg-pulp-paper"
          >
            <Icon name="plus" size={11} />
            {t("START NEW PROJECT")}
          </Link>
        </div>
      )}
    </div>
  );
}

export function SideNav() {
  const { name } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { data: status } = useProjectStatus(name);
  const { data: projects } = useProjects();
  const { handleRun, isPending } = useRunAction();
  const approveStage = useApproveStage();
  const [pipelineCollapsed, setPipelineCollapsed] = useState(false);
  const { stageName, statusName, t } = useI18n();

  const current = projects?.find((p) => p.name === name);
  const activeRoute = location.pathname.split("/").pop() ?? "";

  const handleApprove = (stage: string) => {
    if (!name) return;
    approveStage.mutate({ project: name, stage });
  };

  const settingsPath = name ? `/project/${encodeURIComponent(name)}/settings` : "/settings";
  const isSettingsActive = location.pathname.endsWith("/settings");

  return (
    <aside className="hidden w-[188px] shrink-0 flex-col border-r-[2px] border-ink-black bg-sidebar-tint md:flex">
      <div className="border-b-[2px] border-ink-black p-3">
        <ProjectSwitcher current={current} projects={projects} />

        {name && (
          <Button
            onClick={() => handleRun(name)}
            disabled={isPending}
            size="sm"
            className="mt-2.5 flex w-full items-center justify-center gap-1.5 py-2 font-semibold tracking-[0.14em]"
          >
            {isPending ? t("RUNNING…") : t("NEW CHAPTER")}
          </Button>
        )}
      </div>

      <nav aria-label="Project tools" className="flex flex-col border-b-[2px] border-ink-black py-1">
        {NAV_ITEMS.map((item) => {
          if (item.projectOnly && !name) return null;
          const isActive = activeRoute === item.route;
          const to = name ? `/project/${encodeURIComponent(name)}/${item.route}` : `/${item.route}`;
          return (
            <button
              key={item.label}
              type="button"
              onClick={() => navigate(to)}
              className={`flex items-center gap-2.5 px-4 py-2 text-left transition-colors ${
                isActive
                  ? "bg-hero-red text-bristol"
                  : "text-ink-black/78 hover:bg-ink-black/5"
              }`}
            >
              <Icon name={item.icon} size={13} className={isActive ? "text-bristol" : "text-ink-black/70"} />
              <span className="font-body text-[0.78rem]">{t(item.label)}</span>
            </button>
          );
        })}
      </nav>

      <nav aria-label="Pipeline stages" className="flex-1 overflow-y-auto">
        {name && status ? (
          <div>
            <button
              onClick={() => setPipelineCollapsed((v) => !v)}
              aria-expanded={!pipelineCollapsed}
              className="flex w-full items-center justify-between border-b border-ink-black/15 px-4 py-3"
            >
              <span className="font-meta text-[0.52rem] tracking-[0.18em] text-ink-black/55">
                {t("PIPELINE")}
              </span>
              <Icon
                name="chevron-down"
                size={10}
                className={`text-ink-black/40 transition-transform ${pipelineCollapsed ? "-rotate-90" : ""}`}
              />
            </button>

            {!pipelineCollapsed && (
              <div>
                {STAGE_ORDER.map((stage) => {
                  const info = status.stages[stage];
                  if (!info) return null;
                  const needsApproval = info.status === "awaiting_review";
                  return (
                    <div
                      key={stage}
                      className="flex items-center gap-2 border-b border-ink-black/10 px-4 py-2"
                    >
                      <span
                        className={`h-3 w-3 shrink-0 border border-ink-black text-[0.35rem] flex items-center justify-center ${stageBadgeStyle(info.status)}`}
                      >
                        ●
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="font-body text-[0.72rem] font-medium truncate">
                          {stageName(stage)}
                        </div>
                        <div className="font-meta text-[0.42rem] tracking-[0.14em] text-ink-black/45">
                          {statusName(info.status)}{" "}
                          {info.items_done > 0 ? `${info.items_done}/${info.items_total}` : ""}
                        </div>
                      </div>
                      {needsApproval && (
                        <Button
                          onClick={() => handleApprove(stage)}
                          disabled={approveStage.isPending}
                          size="xs"
                        >
                          {t("APPROVE")}
                        </Button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        ) : (
          <div className="px-4 py-4 font-meta text-[0.56rem] tracking-[0.14em] text-ink-black/40">
            {t("NO PROJECT SELECTED")}
          </div>
        )}
      </nav>

      <div className="border-t-[2px] border-ink-black py-2">
        <Link
          to={settingsPath}
          className={`flex items-center gap-2.5 px-4 py-2 text-[0.76rem] transition-colors ${
            isSettingsActive
              ? "bg-hero-red text-bristol"
              : "text-ink-black/78 hover:bg-ink-black/5"
          }`}
        >
          <Icon name="settings" size={12} className={isSettingsActive ? "text-bristol" : ""} />
          {t("Settings")}
        </Link>
        <a
          href="https://github.com/anthropics/canary/issues"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-2.5 px-4 py-2 text-[0.76rem] text-ink-black/78 hover:bg-ink-black/5"
        >
          <Icon name="support" size={12} />
          {t("Support")}
        </a>
      </div>
    </aside>
  );
}

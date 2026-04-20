import { useEffect, useRef, useState } from "react";
import { useParams, useNavigate, useLocation, Link } from "react-router-dom";
import {
  useProjectStatus,
  useApproveStage,
  useProjects,
  useRunPipeline,
} from "../api/queries";
import { usePipelineStore } from "../store/pipeline";
import { STAGE_ORDER, STAGE_ROUTES } from "../types/api";
import type { StageStatus, ProjectSummary } from "../types/api";
import { Button } from "../components/ui/Button";
import { Icon } from "../components/ui/Icon";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";

function stageBadgeStyle(status: StageStatus) {
  if (status === "complete") return "bg-archive-sage text-bristol";
  if (status === "running") return "bg-narrator-gold text-ink-black";
  if (status === "awaiting_review") return "bg-hero-red text-bristol";
  if (status === "failed") return "bg-hero-red text-bristol";
  return "bg-pulp-paper text-ink-black/45";
}

function stageIcon(status: StageStatus): "check" | "play" | "alert" | "circle" {
  if (status === "complete") return "check";
  if (status === "running") return "play";
  if (status === "awaiting_review" || status === "failed") return "alert";
  return "circle";
}

type NavRoute = "styles" | "settings";

const NAV_ITEMS: { icon: "styles" | "settings"; label: string; route: NavRoute; projectOnly?: boolean }[] = [
  { icon: "styles", label: "Styles", route: "styles", projectOnly: true },
];

function ProjectSwitcher({
  current,
  projects,
  collapsed,
}: {
  current: ProjectSummary | undefined;
  projects: ProjectSummary[] | undefined;
  collapsed: boolean;
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

  if (collapsed) {
    return (
      <div ref={rootRef} className="relative">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="group flex w-full items-center justify-center p-2 hover:bg-ink-black/5"
        >
          <div className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-full border-[2px] border-ink-black bg-ink-black">
            {coverUrl ? (
              <img src={coverUrl} alt="" className="h-full w-full object-cover" />
            ) : (
              <span className="text-bristol text-[0.6rem]">{current?.project_name?.charAt(0) ?? "?"}</span>
            )}
          </div>
        </button>
        {open && (
          <div className="absolute left-full top-0 z-30 ml-2 flex max-h-[300px] min-w-[200px] flex-col rounded border-[2px] border-ink-black bg-bristol shadow-ink-sm">
            <Link
              to="/"
              onClick={() => setOpen(false)}
              className="flex items-center gap-2 border-b-[2px] border-ink-black px-3 py-2 font-meta text-[0.58rem] tracking-[0.18em] hover:bg-pulp-paper"
            >
              <Icon name="chevron-left" size={11} />
              {t("LIBRARY")}
            </Link>
            <div className="flex-1 overflow-y-auto">
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
                    className={cn(
                      "flex w-full items-center gap-2 px-3 py-2 text-left font-body text-[0.82rem] hover:bg-pulp-paper",
                      isCurrent ? "bg-pulp-paper" : "",
                    )}
                  >
                    <span className="truncate flex-1">{p.project_name}</span>
                    {isCurrent && <Icon name="check" size={11} className="text-hero-red" />}
                  </button>
                );
              })}
            </div>
          </div>
        )}
      </div>
    );
  }

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="group flex w-full items-start gap-2.5 border-b-[2px] border-ink-black bg-bristol p-3 text-left hover:bg-pulp-paper"
      >
        <div className="h-11 w-11 shrink-0 overflow-hidden rounded-full border-[2px] border-ink-black bg-ink-black">
          {coverUrl ? (
            <img src={coverUrl} alt="" className="h-full w-full object-cover" />
          ) : (
            <span className="flex h-full w-full items-center justify-center text-bristol text-[0.75rem]">{current?.project_name?.charAt(0) ?? "?"}</span>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="font-display text-[0.9rem] font-bold uppercase leading-[1] tracking-[-0.03em] truncate">
            {current?.project_name ?? t("PROJECT INDEX")}
          </div>
          <div className="mt-1 font-meta text-[0.5rem] tracking-[0.18em] text-ink-black/55">
            NOVEL-TO-INK
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
                  className={cn(
                    "flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-pulp-paper",
                    isCurrent ? "bg-pulp-paper" : "",
                  )}
                >
                  <span className="truncate flex-1 font-body text-[0.82rem]">{p.project_name}</span>
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
  const runPipeline = useRunPipeline();
  const connect = usePipelineStore((state) => state.connect);
  const clearEvents = usePipelineStore((state) => state.clearEvents);
  const approveStage = useApproveStage();
  const [collapsed, setCollapsed] = useState(false);
  const { stageName, statusName, t } = useI18n();

  const current = projects?.find((p) => p.name === name);
  const activeRoute = location.pathname.split("/").pop() ?? "";

  const handleApprove = (stage: string) => {
    if (!name) return;
    approveStage.mutate({ project: name, stage });
  };

  const handleRun = () => {
    if (!name) return;
    clearEvents();
    runPipeline.mutate(
      { project: name },
      { onSuccess: () => connect(name) },
    );
  };

  const settingsPath = name ? `/project/${encodeURIComponent(name)}/settings` : "/settings";
  const isSettingsActive = location.pathname.endsWith("/settings");

  const completedCount = status
    ? STAGE_ORDER.filter((stage) => status.stages[stage]?.status === "complete").length
    : 0;

  const needsApproval = status
    ? STAGE_ORDER.find((stage) => status.stages[stage]?.status === "awaiting_review")
    : null;

  const isRunning = status?.is_running ?? false;

  const continueButtonLabel = () => {
    if (isRunning) return t("RUNNING…");
    if (needsApproval) return "APPROVE & CONTINUE";
    return t("CONTINUE");
  };

  const handleContinue = () => {
    if (!name) return;
    if (isRunning) return;
    if (needsApproval) {
      approveStage.mutate(
        { project: name, stage: needsApproval },
        {
          onSuccess: () => {
            clearEvents();
            runPipeline.mutate(
              { project: name },
              { onSuccess: () => connect(name) },
            );
          },
        }
      );
    } else {
      handleRun();
    }
  };

  if (collapsed) {
    return (
      <aside className="flex h-screen w-[56px] shrink-0 flex-col border-r-[2px] border-ink-black bg-sidebar-tint">
        <div className="flex flex-col items-center border-b-[2px] border-ink-black py-3">
          <ProjectSwitcher current={current} projects={projects} collapsed />
        </div>

        <nav aria-label="Pipeline stages" className="flex-1 overflow-y-auto py-2">
          {name && status && STAGE_ORDER.map((stage) => {
            const info = status.stages[stage];
            if (!info) return null;
            const icon = stageIcon(info.status);
            const isActive = info.status === "running" || info.status === "awaiting_review";
            return (
              <button
                key={stage}
                type="button"
                onClick={() => {
                  const route = STAGE_ROUTES[stage];
                  navigate(`/project/${encodeURIComponent(name)}/${route}`);
                }}
                className={cn(
                  "group relative flex w-full items-center justify-center p-3 transition-colors",
                  isActive ? "bg-ink-black/10" : "hover:bg-ink-black/5",
                )}
                title={`${stageName(stage)}: ${statusName(info.status)}`}
              >
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center rounded-full border-[2px] border-ink-black",
                    stageBadgeStyle(info.status),
                    info.status === "running" && "animate-pulse",
                  )}
                >
                  <Icon name={icon} size={14} />
                </div>
              </button>
            );
          })}
        </nav>

        <div className="flex flex-col items-center border-t-[2px] border-ink-black py-2">
          <button
            type="button"
            onClick={() => setCollapsed(false)}
            className="flex h-10 w-10 items-center justify-center rounded-full border-[2px] border-ink-black bg-pulp-paper hover:bg-ink-black/5"
            title="Expand sidebar"
          >
            <Icon name="chevron-down" size={14} className="rotate-90" />
          </button>
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-screen w-[280px] shrink-0 flex-col border-r-[2px] border-ink-black bg-sidebar-tint">
      <div className="border-b-[2px] border-ink-black">
        <ProjectSwitcher current={current} projects={projects} collapsed={false} />
      </div>

      <div className="border-b-[2px] border-ink-black bg-pulp-paper px-3 py-2">
        <div className="flex items-center justify-between">
          <span className="font-meta text-[0.55rem] tracking-[0.18em] text-ink-black/55">
            {t("PIPELINE")}
          </span>
          <button
            type="button"
            onClick={() => setCollapsed(true)}
            className="rounded border border-ink-black/30 bg-bristol px-1.5 py-0.5 font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/55 hover:bg-ink-black/5"
          >
            COLLAPSE
          </button>
        </div>

        <div className="mt-2 flex items-center gap-1">
          {STAGE_ORDER.map((stage, i) => {
            const info = status?.stages[stage];
            const stageStatus = info?.status ?? "pending";
            const isComplete = stageStatus === "complete";
            const isRunning = stageStatus === "running";
            return (
              <div key={stage} className="flex items-center">
                <div
                  className={cn(
                    "flex h-6 w-6 items-center justify-center rounded-full border border-ink-black text-[0.6rem]",
                    stageBadgeStyle(stageStatus as StageStatus),
                    isRunning && "animate-pulse",
                  )}
                  title={`${stageName(stage)}: ${statusName(stageStatus as StageStatus)}`}
                >
                  {stageStatus === "complete" ? (
                    <Icon name="check" size={10} />
                  ) : stageStatus === "running" ? (
                    <Icon name="play" size={8} />
                  ) : stageStatus === "awaiting_review" || stageStatus === "failed" ? (
                    <Icon name="alert" size={10} />
                  ) : (
                    <Icon name="circle" size={8} />
                  )}
                </div>
                {i < STAGE_ORDER.length - 1 && (
                  <div className={cn("h-[2px] w-3", isComplete ? "bg-archive-sage" : "bg-ink-black/20")} />
                )}
              </div>
            );
          })}
        </div>

        <div className="mt-2 flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden rounded-full border border-ink-black bg-pulp-paper">
            <div
              className="h-full bg-archive-sage transition-all duration-300"
              style={{ width: `${(completedCount / 7) * 100}%` }}
            />
          </div>
          <span className="font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/55">
            {completedCount}/7
          </span>
        </div>
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
              className={cn(
                "flex items-center gap-3 px-4 py-2.5 text-left transition-colors",
                isActive
                  ? "bg-hero-red text-bristol"
                  : "text-ink-black/78 hover:bg-ink-black/5",
              )}
            >
              <Icon name={item.icon} size={14} className={isActive ? "text-bristol" : "text-ink-black/70"} />
              <span className="font-body text-[0.85rem]">{t(item.label)}</span>
            </button>
          );
        })}
      </nav>

      <nav aria-label="Pipeline stages" className="flex-1 overflow-y-auto">
        {name && status ? (
          <div className="py-1">
            {STAGE_ORDER.map((stage) => {
              const info = status.stages[stage];
              if (!info) return null;
              const needsApproval = info.status === "awaiting_review";
              const isActive = info.status === "running" || info.status === "awaiting_review";
              const route = STAGE_ROUTES[stage];

              return (
                <div
                  key={stage}
                  className={cn(
                    "flex items-center gap-3 border-b border-ink-black/10 px-4 py-3 transition-colors",
                    isActive && "bg-ink-black/5",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => navigate(`/project/${encodeURIComponent(name)}/${route}`)}
                    className={cn(
                      "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-[2px] border-ink-black",
                      stageBadgeStyle(info.status),
                      info.status === "running" && "animate-pulse",
                    )}
                  >
                    <Icon name={stageIcon(info.status)} size={14} />
                  </button>
                  <div className="min-w-0 flex-1">
                    <div className="font-body text-[0.9rem] font-medium truncate">
                      {stageName(stage)}
                    </div>
                    <div className={cn(
                      "font-meta text-[0.6rem] tracking-[0.14em]",
                      info.status === "complete" ? "text-archive-sage" :
                      info.status === "running" ? "text-narrator-gold animate-pulse" :
                      info.status === "awaiting_review" || info.status === "failed" ? "text-hero-red" :
                      "text-ink-black/45"
                    )}>
                      {statusName(info.status)}
                      {info.status === "running" && info.items_total > 0 && ` (${info.items_done}/${info.items_total})`}
                    </div>
                  </div>
                  {needsApproval && (
                    <Button
                      onClick={() => handleApprove(stage)}
                      disabled={approveStage.isPending}
                      size="xs"
                      className="shrink-0"
                    >
                      {t("APPROVE")}
                    </Button>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="px-4 py-4 font-meta text-[0.6rem] tracking-[0.14em] text-ink-black/40">
            {t("NO PROJECT SELECTED")}
          </div>
        )}
      </nav>

      <div className="border-t-[2px] border-ink-black p-3">
        {name && (
          <Button
            onClick={handleContinue}
            disabled={isRunning || approveStage.isPending || runPipeline.isPending}
            size="lg"
            className="w-full"
          >
            {isRunning ? (
              <>
                <Icon name="loader" size={14} className="animate-spin" />
                {t("RUNNING…")}
              </>
            ) : (
              <>
                {continueButtonLabel()}
                <Icon name="arrow-right" size={14} />
              </>
            )}
          </Button>
        )}
      </div>

      <div className="border-t-[2px] border-ink-black py-2">
        <Link
          to={settingsPath}
          className={cn(
            "flex items-center gap-3 px-4 py-2.5 text-[0.85rem] transition-colors",
            isSettingsActive
              ? "bg-hero-red text-bristol"
              : "text-ink-black/78 hover:bg-ink-black/5",
          )}
        >
          <Icon name="settings" size={14} className={isSettingsActive ? "text-bristol" : ""} />
          {t("Settings")}
        </Link>
        <a
          href="https://github.com/anthropics/canary/issues"
          target="_blank"
          rel="noreferrer"
          className="flex items-center gap-3 px-4 py-2.5 text-[0.85rem] text-ink-black/78 hover:bg-ink-black/5"
        >
          <Icon name="support" size={14} />
          {t("Support")}
        </a>
      </div>
    </aside>
  );
}

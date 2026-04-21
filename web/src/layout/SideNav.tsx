import { useEffect, useMemo, useRef, useState } from "react";
import { useParams, useNavigate, useLocation, Link } from "react-router-dom";
import {
  useProjectStatus,
  useApproveStage,
  useProjects,
  useRunPipeline,
  useStyles,
} from "../api/queries";
import { usePipelineStore } from "../store/pipeline";
import { STAGE_ORDER, STAGE_ROUTES } from "../types/api";
import type { StageName, StageStatus, ProjectSummary } from "../types/api";
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

type PipelineNavStage = {
  key: StageName | "style";
  route: string;
  label: string;
  status: StageStatus;
  itemsDone: number;
  itemsTotal: number;
  failedCount: number;
  error: string | null;
  needsApproval: boolean;
  activeStyleLabel?: string | null;
};

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
          <div className="flex h-10 w-10 items-center justify-center overflow-hidden border-[2px] border-ink-black bg-ink-black">
            {coverUrl ? (
              <img src={coverUrl} alt="" className="h-full w-full object-cover" />
            ) : (
              <span className="text-bristol text-[0.6rem]">{current?.project_name?.charAt(0) ?? "?"}</span>
            )}
          </div>
        </button>
        {open && (
          <div className="absolute left-full top-0 z-30 ml-2 flex max-h-[300px] min-w-[220px] flex-col border-[2px] border-ink-black bg-bristol shadow-ink-sm">
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
        className="group flex w-full items-start gap-2.5 bg-bristol p-3 text-left hover:bg-pulp-paper"
      >
        <div className="h-11 w-11 shrink-0 overflow-hidden border-[2px] border-ink-black bg-ink-black">
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
  const { data: stylesData } = useStyles(name);
  const runPipeline = useRunPipeline();
  const connect = usePipelineStore((state) => state.connect);
  const clearEvents = usePipelineStore((state) => state.clearEvents);
  const approveStage = useApproveStage();
  const [collapsed, setCollapsed] = useState(false);
  const { stageName, statusName, t } = useI18n();

  const current = projects?.find((p) => p.name === name);

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

  const styleSuggestions = stylesData?.suggestions ?? [];
  const activeStyle = stylesData?.active_index == null
    ? null
    : styleSuggestions.find((s) => s.index === stylesData.active_index) ?? null;
  const styleItemsTotal = styleSuggestions.length;
  const styleItemsDone = styleSuggestions.filter((s) => s.has_sample).length;
  const styleStatus: StageStatus = activeStyle
    ? "complete"
    : styleItemsTotal > 0
      ? "awaiting_review"
      : "pending";

  const pipelineStages = useMemo<PipelineNavStage[]>(() => {
    const stages: PipelineNavStage[] = [];
    for (const stage of STAGE_ORDER) {
      const info = status?.stages[stage];
      stages.push({
        key: stage,
        route: STAGE_ROUTES[stage],
        label: stageName(stage),
        status: info?.status ?? "pending",
        itemsDone: info?.items_done ?? 0,
        itemsTotal: info?.items_total ?? 0,
        failedCount: info?.items_failed.length ?? 0,
        error: info?.error ?? null,
        needsApproval: info?.status === "awaiting_review",
      });
      if (stage === "extract") {
        stages.push({
          key: "style",
          route: "styles",
          label: t("Styles").toUpperCase(),
          status: styleStatus,
          itemsDone: styleItemsDone,
          itemsTotal: styleItemsTotal,
          failedCount: 0,
          error: null,
          needsApproval: false,
          activeStyleLabel: activeStyle?.label ?? null,
        });
      }
    }
    return stages;
  }, [activeStyle?.label, stageName, status?.stages, styleItemsDone, styleItemsTotal, styleStatus, t]);

  const completedCount = pipelineStages.filter((stage) => stage.status === "complete").length;

  const needsApproval = status
    ? STAGE_ORDER.find((stage) => status.stages[stage]?.status === "awaiting_review")
    : null;
  const styleNeedsSelection =
    !!name &&
    status?.stages.extract?.status === "complete" &&
    styleStatus !== "complete";

  const isRunning = status?.is_running ?? false;

  const continueButtonLabel = () => {
    if (isRunning) return t("RUNNING…");
    if (needsApproval) return "APPROVE & CONTINUE";
    if (styleNeedsSelection) return "PICK STYLE";
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
    } else if (styleNeedsSelection) {
      navigate(`/project/${encodeURIComponent(name)}/styles`);
    } else {
      handleRun();
    }
  };

  if (collapsed) {
    return (
      <aside className="flex h-screen w-[72px] shrink-0 flex-col border-r-[2px] border-ink-black bg-sidebar-tint">
        <div className="flex flex-col items-center border-b-[2px] border-ink-black py-2">
          <button
            type="button"
            onClick={() => setCollapsed(false)}
            className="mb-2 flex h-8 w-8 items-center justify-center border-[2px] border-ink-black bg-bristol hover:bg-pulp-paper"
            title="Expand sidebar"
          >
            <Icon name="chevron-left" size={13} />
          </button>
          <ProjectSwitcher current={current} projects={projects} collapsed />
        </div>

        <nav aria-label="Pipeline stages" className="flex-1 overflow-y-auto py-2">
          {name && pipelineStages.map((stage) => {
            const icon = stageIcon(stage.status);
            const isActive = stage.status === "running" || stage.status === "awaiting_review";
            return (
              <button
                key={stage.key}
                type="button"
                onClick={() => {
                  navigate(`/project/${encodeURIComponent(name)}/${stage.route}`);
                }}
                className={cn(
                  "group relative flex w-full items-center justify-center p-3 transition-colors",
                  isActive ? "bg-ink-black/10" : "hover:bg-ink-black/5",
                )}
                title={`${stage.label}: ${statusName(stage.status)}`}
              >
                <div
                  className={cn(
                    "flex h-8 w-8 items-center justify-center border-[2px] border-ink-black",
                    stageBadgeStyle(stage.status),
                    stage.status === "running" && "animate-pulse",
                  )}
                >
                  <Icon name={icon} size={14} />
                </div>
              </button>
            );
          })}
        </nav>
      </aside>
    );
  }

  return (
    <aside className="flex h-screen w-[260px] shrink-0 flex-col border-r-[2px] border-ink-black bg-sidebar-tint">
      <div className="flex items-stretch border-b-[2px] border-ink-black">
        <div className="min-w-0 flex-1">
          <ProjectSwitcher current={current} projects={projects} collapsed={false} />
        </div>
        <button
          type="button"
          onClick={() => setCollapsed(true)}
          className="border-l-[2px] border-ink-black bg-pulp-paper px-2 font-meta text-[0.48rem] tracking-[0.14em] text-ink-black/65 hover:bg-bristol"
          title="Collapse sidebar"
        >
          <span className="[writing-mode:vertical-rl] rotate-180">COLLAPSE</span>
        </button>
      </div>

      <nav aria-label="Pipeline stages" className="flex-1 overflow-y-auto">
        {name ? (
          <div className="py-1">
            {pipelineStages.map((stage) => {
              const isActive = stage.status === "running" || stage.status === "awaiting_review";

              return (
                <div
                  key={stage.key}
                  className={cn(
                    "flex items-stretch border-b border-ink-black/10 transition-colors",
                    isActive && "bg-ink-black/5",
                  )}
                >
                  <button
                    type="button"
                    onClick={() => navigate(`/project/${encodeURIComponent(name)}/${stage.route}`)}
                    className="flex min-w-0 flex-1 items-center gap-3 px-4 py-3 text-left hover:bg-ink-black/5"
                  >
                    <div
                      className={cn(
                        "flex h-8 w-8 shrink-0 items-center justify-center border-[2px] border-ink-black",
                        stageBadgeStyle(stage.status),
                        stage.status === "running" && "animate-pulse",
                      )}
                    >
                      <Icon name={stageIcon(stage.status)} size={14} />
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="truncate font-body text-[0.85rem] font-medium">
                        {stage.label}
                      </div>
                      <div className={cn(
                        "font-meta text-[0.55rem] tracking-[0.14em]",
                        stage.status === "complete" ? "text-archive-sage" :
                        stage.status === "running" ? "text-narrator-gold animate-pulse" :
                        stage.status === "awaiting_review" || stage.status === "failed" ? "text-hero-red" :
                        "text-ink-black/45"
                      )}>
                        {statusName(stage.status)}
                        {stage.itemsTotal > 0 && ` · ${stage.itemsDone}/${stage.itemsTotal}`}
                        {stage.failedCount > 0 && ` · ${stage.failedCount} FAILED`}
                      </div>
                      {stage.activeStyleLabel && (
                        <div className="mt-0.5 truncate font-meta text-[0.5rem] tracking-[0.12em] text-archive-sage">
                          ACTIVE: {stage.activeStyleLabel.toUpperCase()}
                        </div>
                      )}
                      {stage.error && (
                        <div className="mt-0.5 truncate font-meta text-[0.5rem] tracking-[0.12em] text-hero-red">
                          {stage.error}
                        </div>
                      )}
                      {stage.itemsTotal > 0 && (
                        <div className="mt-1 h-1.5 w-full overflow-hidden border border-ink-black/35 bg-pulp-paper">
                          <div
                            className={cn(
                              "h-full transition-all duration-300",
                              stage.status === "failed" ? "bg-hero-red" : "bg-archive-sage",
                            )}
                            style={{ width: `${Math.max(0, Math.min(100, (stage.itemsDone / stage.itemsTotal) * 100))}%` }}
                          />
                        </div>
                      )}
                    </div>
                  </button>
                  {stage.needsApproval && (
                    <Button
                      onClick={(event) => {
                        event.stopPropagation();
                        if (stage.key !== "style") handleApprove(stage.key);
                      }}
                      disabled={approveStage.isPending}
                      size="xs"
                      className="mr-3 self-center shrink-0"
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
            size="sm"
            className="w-full py-2"
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
        <div className="mt-2 flex items-center gap-2">
          <div className="h-1.5 flex-1 overflow-hidden border border-ink-black bg-pulp-paper">
            <div
              className="h-full bg-archive-sage transition-all duration-300"
              style={{ width: `${(completedCount / Math.max(1, pipelineStages.length)) * 100}%` }}
            />
          </div>
          <span className="font-meta text-[0.5rem] tracking-[0.14em] text-ink-black/55">
            {completedCount}/{pipelineStages.length}
          </span>
        </div>
      </div>

      <div className="border-t-[2px] border-ink-black py-2">
        <Link
          to={settingsPath}
          className={cn(
            "flex items-center gap-2.5 px-4 py-2 text-[0.78rem] transition-colors",
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
          className="flex items-center gap-2.5 px-4 py-2 text-[0.78rem] text-ink-black/78 hover:bg-ink-black/5"
        >
          <Icon name="support" size={14} />
          {t("Support")}
        </a>
      </div>
    </aside>
  );
}

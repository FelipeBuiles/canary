import { useMemo } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useProjectStatus,
  useProjects,
  useRunPipeline,
  useStyles,
} from "../api/queries";
import { Icon } from "../components/ui/Icon";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";
import { usePipelineStore } from "../store/pipeline";
import { STAGE_ORDER, STAGE_ROUTES } from "../types/api";
import type { StageName, StageStatus } from "../types/api";

type PipelineNavStage = {
  key: StageName | "style";
  route: string;
  label: string;
  status: StageStatus;
  itemsDone: number;
  itemsTotal: number;
  failedCount: number;
  needsApproval: boolean;
  detail?: string | null;
};

interface SideNavProps {
  showDesktop?: boolean;
}

function progressWidth(stage: PipelineNavStage) {
  if (stage.status === "complete" || stage.status === "awaiting_review") return 100;
  if (stage.status === "running") {
    if (stage.itemsTotal > 0) return Math.max(8, Math.min(100, (stage.itemsDone / stage.itemsTotal) * 100));
    return 60;
  }
  return 0;
}

function progressTone(stage: PipelineNavStage) {
  if (stage.status === "failed") return "bg-hero-red";
  if (stage.status === "running") return "bg-narrator-gold";
  return "bg-archive-sage";
}

function stageDetail(stage: PipelineNavStage) {
  if (stage.detail) return stage.detail;
  if (stage.failedCount > 0) return `${stage.failedCount} failed`;
  if (stage.status === "pending") return null;
  if (stage.itemsTotal <= 0) return null;
  if (stage.key === "prompts") return `${stage.itemsDone} prompts compiled`;
  if (stage.key === "generate") return `${stage.itemsDone} panels drawn`;
  if (stage.key === "assemble") return `${stage.itemsDone} pages`;
  if (stage.key === "index") return `${stage.itemsDone} refs`;
  if (stage.key === "style") return `${stage.itemsDone} samples`;
  if (stage.status === "running") return `${stage.itemsDone}/${stage.itemsTotal}`;
  return `${stage.itemsDone} items`;
}

export function SideNav({ showDesktop = true }: SideNavProps) {
  const { name } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { stageName, t } = useI18n();
  const { data: status } = useProjectStatus(name);
  const { data: projects } = useProjects();
  const { data: stylesData } = useStyles(name);
  const runPipeline = useRunPipeline();
  const approveStage = useApproveStage();
  const connect = usePipelineStore((state) => state.connect);
  const clearEvents = usePipelineStore((state) => state.clearEvents);

  const current = projects?.find((p) => p.name === name);
  const projectTitle = current?.project_name ?? name ?? t("PROJECT INDEX");
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
          needsApproval: false,
          detail: activeStyle ? activeStyle.label : null,
        });
      }
    }
    return stages;
  }, [activeStyle, stageName, status?.stages, styleItemsDone, styleItemsTotal, styleStatus, t]);

  const activeStageRoute = pipelineStages.find((stage) =>
    location.pathname.endsWith(`/${stage.route}`),
  )?.route ?? pipelineStages[0]?.route ?? "";

  const needsApproval = status
    ? STAGE_ORDER.find((stage) => status.stages[stage]?.status === "awaiting_review")
    : null;
  const styleNeedsSelection =
    !!name &&
    status?.stages.extract?.status === "complete" &&
    styleStatus !== "complete";
  const isRunning = status?.is_running ?? false;

  function handleRun() {
    if (!name) return;
    clearEvents();
    runPipeline.mutate(
      { project: name },
      { onSuccess: () => connect(name) },
    );
  }

  function handleContinue() {
    if (!name || isRunning) return;
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
        },
      );
      return;
    }
    if (styleNeedsSelection) {
      navigate(`/project/${encodeURIComponent(name)}/styles`);
      return;
    }
    handleRun();
  }

  function continueButtonLabel() {
    if (isRunning) return t("RUNNING…");
    if (needsApproval) return "APPROVE & CONTINUE";
    if (styleNeedsSelection) return "PICK STYLE";
    return "NEXT STAGE";
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
      {name && (
        <select
          aria-label={t("PIPELINE STAGE")}
          value={activeStageRoute}
          onChange={(event) => navigate(`/project/${encodeURIComponent(name)}/${event.target.value}`)}
          className="max-w-[9.5rem] border border-bristol/20 bg-ink-black px-2 py-2 font-meta text-[0.56rem] tracking-[0.12em] text-bristol"
        >
          {pipelineStages.map((stage) => (
            <option key={stage.key} value={stage.route}>{stage.label}</option>
          ))}
        </select>
      )}
    </header>
  );

  if (!showDesktop) return <>{mobileNav}</>;

  return (
    <>
      {mobileNav}
      <aside className="hidden h-screen w-[200px] shrink-0 flex-col bg-ink-black text-bristol md:flex">
        <Link
          to="/"
          className="flex items-center gap-3 border-b border-bristol/10 px-4 py-4"
          aria-label={t("LIBRARY")}
        >
          <span className="flex h-11 w-11 shrink-0 items-center justify-center bg-pulp-paper font-display text-[0.85rem] font-black text-ink-black">
            {projectTitle.charAt(0)}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-display text-[0.82rem] font-black uppercase leading-none tracking-[-0.02em]">
              {projectTitle}
            </span>
            <span className="mt-1 block font-meta text-[0.5rem] tracking-[0.16em] text-bristol/38">
              ← {t("LIBRARY")}
            </span>
          </span>
        </Link>

        <nav aria-label="Pipeline stages" className="flex-1 overflow-y-auto py-3">
          {name ? pipelineStages.map((stage) => {
            const isActive = activeStageRoute === stage.route;
            const detail = stageDetail(stage);
            return (
              <button
                key={stage.key}
                type="button"
                onClick={() => navigate(`/project/${encodeURIComponent(name)}/${stage.route}`)}
                className={cn(
                  "w-full border-l-[3px] px-4 py-3 text-left transition-colors",
                  isActive
                    ? "border-hero-red bg-hero-red/25"
                    : "border-transparent hover:bg-bristol/5",
                )}
              >
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "font-meta text-[0.62rem] tracking-[0.14em]",
                    isActive ? "text-bristol" : "text-bristol/68",
                  )}>
                    {stage.label}
                  </span>
                  {(stage.status === "complete" || stage.status === "awaiting_review") && (
                    <span className="ml-auto text-[0.78rem] leading-none text-archive-sage">✓</span>
                  )}
                  {stage.status === "failed" && (
                    <span className="ml-auto text-[0.78rem] leading-none text-hero-red">!</span>
                  )}
                </div>
                <div className="mt-2 h-[3px] bg-bristol/10">
                  <div
                    className={cn("h-full transition-all duration-300", progressTone(stage))}
                    style={{ width: `${progressWidth(stage)}%` }}
                  />
                </div>
                {detail && (
                  <div className="mt-1.5 font-meta text-[0.5rem] tracking-[0.06em] text-bristol/38">
                    {detail}
                  </div>
                )}
              </button>
            );
          }) : (
            <div className="px-4 py-4 font-meta text-[0.6rem] tracking-[0.14em] text-bristol/35">
              {t("NO PROJECT SELECTED")}
            </div>
          )}
        </nav>

        <div className="border-t border-bristol/10 p-3">
          {name && (
            <button
              type="button"
              onClick={handleContinue}
              disabled={isRunning || approveStage.isPending || runPipeline.isPending}
              className="flex min-h-12 w-full items-center justify-center gap-2 border-[2px] border-ink-black/80 bg-hero-red px-3 py-2 font-meta text-[0.62rem] tracking-[0.16em] text-bristol shadow-ink-sm transition-colors hover:bg-hero-red/90 disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none"
            >
              {isRunning && <Icon name="loader" size={14} className="animate-spin" />}
              {continueButtonLabel()} {!isRunning && "→"}
            </button>
          )}
          <div className="mt-3 flex justify-center gap-3 font-meta text-[0.5rem] tracking-[0.08em] text-bristol/30">
            <Link to={settingsPath} className={isSettingsActive ? "text-bristol" : "hover:text-bristol/60"}>
              {t("Settings")}
            </Link>
            <span>·</span>
            <a href="https://github.com/anthropics/canary/issues" target="_blank" rel="noreferrer" className="hover:text-bristol/60">
              {t("Support")}
            </a>
          </div>
        </div>
      </aside>
    </>
  );
}

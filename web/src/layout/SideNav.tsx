import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import {
  useApproveStage,
  useImages,
  usePages,
  usePanelSummaries,
  useProjectStatus,
  useProjects,
  usePromptSummaries,
  useRunPipeline,
  useScreenplays,
  useStoryBible,
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

function plural(count: number, singular: string, pluralForm = `${singular}s`) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
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
  if (stage.status === "running" || stage.status === "awaiting_review") return "bg-narrator-gold";
  if (stage.status === "pending") return "bg-bristol/18";
  return "bg-archive-sage";
}

function stageStatusLabel(stage: PipelineNavStage) {
  if (stage.failedCount > 0 || stage.status === "failed") return "FAILED";
  if (stage.status === "awaiting_review") return "REVIEW";
  if (stage.status === "running") return "RUNNING";
  if (stage.status === "complete") return "DONE";
  return "PENDING";
}

function stageStatusGlyph(stage: PipelineNavStage) {
  if (stage.failedCount > 0 || stage.status === "failed") return "!";
  if (stage.status === "awaiting_review") return "REVIEW";
  if (stage.status === "running") return "RUN";
  if (stage.status === "complete") return "OK";
  return "WAIT";
}

function stageDetail(stage: PipelineNavStage, fallbackDetail?: string | null) {
  if (stage.detail) return stage.detail;
  if (fallbackDetail) return fallbackDetail;
  if (stage.failedCount > 0) return `${stage.failedCount} failed`;
  if (stage.itemsTotal > 0) return `${stage.itemsDone}/${stage.itemsTotal}`;
  return "Not started";
}

export function SideNav({ showDesktop = true }: SideNavProps) {
  const { name } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { stageName, t } = useI18n();
  const navRef = useRef<HTMLElement>(null);
  const [compactStageDetails, setCompactStageDetails] = useState(false);
  const { data: status } = useProjectStatus(name);
  const { data: projects } = useProjects();
  const { data: stylesData } = useStyles(name);
  const storyBibleReady =
    status?.stages.extract?.status === "awaiting_review" ||
    status?.stages.extract?.status === "complete";
  const screenplayReady = status?.stages.screenplay?.status != null && status.stages.screenplay.status !== "pending";
  const panelsReady = status?.stages.panels?.status != null && status.stages.panels.status !== "pending";
  const promptsReady = status?.stages.prompts?.status != null && status.stages.prompts.status !== "pending";
  const generateReady = status?.stages.generate?.status != null && status.stages.generate.status !== "pending";
  const assembleReady = status?.stages.assemble?.status != null && status.stages.assemble.status !== "pending";
  const { data: storyBible } = useStoryBible(name, storyBibleReady);
  const { data: screenplays } = useScreenplays(screenplayReady ? name : undefined);
  const { data: panelSummaries } = usePanelSummaries(panelsReady ? name : undefined);
  const { data: promptSummaries } = usePromptSummaries(promptsReady ? name : undefined);
  const { data: images } = useImages(generateReady ? name : undefined);
  const { data: pages } = usePages(assembleReady ? name : undefined);
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

  const stageDetails = useMemo<Record<string, string>>(() => {
    const details: Record<string, string> = {};

    if (storyBible) {
      details.extract = [
        plural(storyBible.scenes.length, "scene"),
        plural(storyBible.characters.length, "character"),
        plural(storyBible.locations.length, "location"),
      ].join(" · ");
      details.index = [
        plural(storyBible.characters.length, "character ref"),
        plural(storyBible.locations.length, "location plate"),
      ].join(" · ");
    }

    if (styleItemsTotal > 0) {
      details.style = activeStyle
        ? activeStyle.label
        : `${styleItemsDone}/${styleItemsTotal} samples`;
    }

    if (screenplays?.length) {
      const beatCount = screenplays.reduce((sum, screenplay) => sum + screenplay.beat_count, 0);
      details.screenplay = [
        plural(screenplays.length, "scene"),
        plural(beatCount, "beat"),
      ].join(" · ");
    }

    if (panelSummaries?.length) {
      const panelCount = panelSummaries.reduce((sum, scene) => sum + scene.panel_count, 0);
      details.panels = [
        plural(panelSummaries.length, "scene"),
        plural(panelCount, "panel"),
      ].join(" · ");
    }

    if (promptSummaries?.length) {
      const promptCount = promptSummaries.reduce((sum, scene) => sum + scene.prompt_count, 0);
      details.prompts = plural(promptCount, "prompt");
    }

    if (images?.length) {
      const acceptedCount = images.filter((image) => image.status === "done").length;
      details.generate = `${acceptedCount}/${images.length} accepted`;
    }

    if (pages?.length) {
      const pagePanelCount = pages.reduce((sum, page) => sum + page.panel_count, 0);
      details.assemble = [
        plural(pages.length, "page"),
        plural(pagePanelCount, "panel"),
      ].join(" · ");
    }

    return details;
  }, [
    activeStyle,
    images,
    pages,
    panelSummaries,
    promptSummaries,
    screenplays,
    storyBible,
    styleItemsDone,
    styleItemsTotal,
  ]);

  const needsApproval = status
    ? STAGE_ORDER.find((stage) => status.stages[stage]?.status === "awaiting_review")
    : null;
  const styleNeedsSelection =
    !!name &&
    status?.stages.extract?.status === "complete" &&
    styleStatus !== "complete";
  const isRunning = status?.is_running ?? false;

  const measureStageDetails = useCallback(() => {
    const nav = navRef.current;
    if (!nav) return;

    // Temporarily show all detail divs to measure natural height
    const detailDivs = nav.querySelectorAll<HTMLElement>("[data-stage-detail]");
    detailDivs.forEach((el) => el.classList.remove("hidden"));

    const needsCompactDetails = nav.scrollHeight > nav.clientHeight + 1;

    // Re-apply compact state
    if (needsCompactDetails) {
      detailDivs.forEach((el) => {
        if (!el.dataset.active) el.classList.add("hidden");
      });
    }

    setCompactStageDetails((current) =>
      current === needsCompactDetails ? current : needsCompactDetails,
    );
  }, []);

  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;

    const frame = requestAnimationFrame(measureStageDetails);
    const observer = new ResizeObserver(measureStageDetails);
    observer.observe(nav);

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [measureStageDetails, pipelineStages, stageDetails, activeStageRoute]);

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

  function renderStageRow(stage: PipelineNavStage) {
    const isActive = activeStageRoute === stage.route;
    const detail = stageDetail(stage, stageDetails[stage.key]);
    const statusLabel = stageStatusLabel(stage);
    const statusGlyph = stageStatusGlyph(stage);
    const rowClassName = cn(
      "w-full border-l-[3px] px-5 py-4 text-left transition-colors xl:px-6 xl:py-4 2xl:py-5 min-[2200px]:border-l-[5px] min-[2200px]:px-9 min-[2200px]:py-7",
      isActive
        ? "border-narrator-gold bg-bristol/8"
        : "border-transparent hover:bg-bristol/5",
    );

    return (
      <button
        key={stage.key}
        type="button"
        onClick={() => name && navigate(`/project/${encodeURIComponent(name)}/${stage.route}`)}
        aria-label={`${stage.label}: ${statusLabel}. ${detail}`}
        className={rowClassName}
      >
        <div className="flex items-center gap-2">
          <span className={cn(
            "font-meta text-[0.74rem] tracking-[0.16em] 2xl:text-[0.84rem] min-[2200px]:text-[1.25rem] min-[2200px]:tracking-[0.18em]",
            isActive ? "text-bristol" : "text-bristol/68",
          )}>
            {stage.label}
          </span>
          <span
            className={cn(
              "ml-auto font-meta text-[0.5rem] leading-none tracking-[0.12em] 2xl:text-[0.56rem] min-[2200px]:text-[0.82rem]",
              stage.status === "complete" && stage.failedCount === 0 && "text-archive-sage",
              (stage.status === "running" || stage.status === "awaiting_review") && "text-narrator-gold",
              (stage.status === "failed" || stage.failedCount > 0) && "text-hero-red",
              stage.status === "pending" && stage.failedCount === 0 && "text-bristol/32",
            )}
          >
            {statusGlyph}
          </span>
        </div>
        <div className="mt-2.5 h-[4px] bg-bristol/10 min-[2200px]:mt-4 min-[2200px]:h-[6px]">
          <div
            className={cn("h-full transition-all duration-300", progressTone(stage))}
            style={{ width: `${progressWidth(stage)}%` }}
          />
        </div>
        <div
          data-stage-detail
          {...(isActive ? { "data-active": "" } : {})}
          className={cn(
            "mt-2 font-meta text-[0.62rem] tracking-[0.06em] 2xl:text-[0.72rem] min-[2200px]:mt-3 min-[2200px]:text-[1rem]",
            compactStageDetails && !isActive && "hidden",
            isActive ? "text-bristol/62" : "text-bristol/42",
          )}
        >
          {detail}
        </div>
      </button>
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
      <aside className="hidden h-screen w-[240px] shrink-0 flex-col bg-ink-black text-bristol md:flex xl:w-[270px] 2xl:w-[320px] min-[2200px]:w-[430px]">
        <Link
          to="/"
          className="flex items-center gap-4 border-b border-bristol/10 px-5 py-5 xl:px-6 xl:py-6 min-[2200px]:gap-6 min-[2200px]:px-9 min-[2200px]:py-8"
          aria-label={t("LIBRARY")}
        >
          <span className="flex h-12 w-12 shrink-0 items-center justify-center bg-pulp-paper font-display text-[0.92rem] font-black text-ink-black 2xl:h-14 2xl:w-14 2xl:text-[1rem] min-[2200px]:h-20 min-[2200px]:w-20 min-[2200px]:text-[1.35rem]">
            {projectTitle.charAt(0)}
          </span>
          <span className="min-w-0">
            <span className="block truncate font-display text-[0.98rem] font-black uppercase leading-none tracking-[-0.02em] 2xl:text-[1.12rem] min-[2200px]:text-[1.7rem]">
              {projectTitle}
            </span>
            <span className="mt-1.5 block font-meta text-[0.56rem] tracking-[0.16em] text-bristol/38 2xl:text-[0.64rem] min-[2200px]:text-[0.92rem]">
              ← {t("LIBRARY")}
            </span>
          </span>
        </Link>

        <div className="relative min-h-0 flex-1">
          <nav ref={navRef} aria-label="Pipeline stages" className="h-full overflow-y-auto py-4 2xl:py-5 min-[2200px]:py-8">
            {name ? pipelineStages.map((stage) => renderStageRow(stage)) : (
              <div className="px-4 py-4 font-meta text-[0.6rem] tracking-[0.14em] text-bristol/35">
                {t("NO PROJECT SELECTED")}
              </div>
            )}
          </nav>
        </div>

        <div className="border-t border-bristol/10 p-4 2xl:p-5 min-[2200px]:p-7">
          {name && (
            <button
              type="button"
              onClick={handleContinue}
              disabled={isRunning || approveStage.isPending || runPipeline.isPending}
              className="flex min-h-13 w-full items-center justify-center gap-2 border-[2px] border-ink-black/80 bg-hero-red px-3 py-3 font-meta text-[0.72rem] tracking-[0.18em] text-bristol shadow-ink-sm transition-colors hover:bg-hero-red/90 disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none 2xl:min-h-14 2xl:text-[0.82rem] min-[2200px]:min-h-20 min-[2200px]:text-[1.15rem]"
            >
              {isRunning && <Icon name="loader" size={14} className="animate-spin" />}
              {continueButtonLabel()} {!isRunning && "→"}
            </button>
          )}
          <div className="mt-4 flex justify-center gap-3 font-meta text-[0.58rem] tracking-[0.08em] text-bristol/30 2xl:text-[0.66rem] min-[2200px]:mt-6 min-[2200px]:text-[1rem]">
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

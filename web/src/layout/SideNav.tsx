import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { ConfirmDrawer } from "../components/ui/ConfirmDrawer";
import {
  useApproveStage,
  useCreditBalance,
  useImages,
  usePages,
  usePanelSummaries,
  useProjectStatus,
  useProjects,
  usePromptSummaries,
  useRunPipeline,
  useScreenplays,
  useStageEstimate,
  useStoryBible,
  useStyles,
} from "../api/queries";
import { maybeShowInsufficientCredits, useInsufficientCreditsStore } from "../store/insufficientCredits";
import { Icon } from "../components/ui/Icon";
import { useI18n } from "../i18n";
import { cn } from "../lib/cn";
import { getShotPlanAction, getShotPlanSubStatus } from "../lib/shotPlan";
import { getBackendStageUiLabel, UI_STAGES } from "../lib/uiStages";
import { usePipelineStore } from "../store/pipeline";
import { STAGE_ORDER } from "../types/api";
import type { StageName, StageStatus } from "../types/api";
import type { UiStageKey } from "../lib/uiStages";

type PipelineNavStage = {
  key: UiStageKey;
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
  if (stage.status === "complete" && stage.failedCount > 0) return "bg-narrator-gold";
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
  const { id: projectId } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useI18n();
  const navRef = useRef<HTMLElement>(null);
  const [compactStageDetails, setCompactStageDetails] = useState(false);
  const { data: status } = useProjectStatus(projectId);
  const { data: projects } = useProjects();
  const { data: stylesData } = useStyles(projectId);
  const storyBibleReady =
    status?.stages.extract?.status === "awaiting_review" ||
    status?.stages.extract?.status === "complete";
  const adaptReady = status?.stages.adapt?.status != null && status.stages.adapt.status !== "pending";
  const planReady = status?.stages.plan?.status != null && status.stages.plan.status !== "pending";
  const storyboardReady = status?.stages.storyboard?.status != null && status.stages.storyboard.status !== "pending";
  const directReady = status?.stages.direct?.status != null && status.stages.direct.status !== "pending";
  const drawReady = status?.stages.draw?.status != null && status.stages.draw.status !== "pending";
  const composeReady = status?.stages.compose?.status != null && status.stages.compose.status !== "pending";
  const { data: storyBible } = useStoryBible(projectId, storyBibleReady);
  const { data: screenplays } = useScreenplays(adaptReady ? projectId : undefined);
  const { data: panelSummaries } = usePanelSummaries(planReady || storyboardReady ? projectId : undefined);
  const { data: promptSummaries } = usePromptSummaries(directReady ? projectId : undefined);
  const { data: images } = useImages(drawReady ? projectId : undefined);
  const { data: pages } = usePages(composeReady ? projectId : undefined);
  const runPipeline = useRunPipeline();
  const approveStage = useApproveStage();
  const connect = usePipelineStore((state) => state.connect);
  const clearEvents = usePipelineStore((state) => state.clearEvents);
  const shotPlanAction = useMemo(() => getShotPlanAction(status), [status]);

  const current = projects?.find((p) => p.id === projectId);
  const projectTitle = current?.project_name ?? projectId ?? t("PROJECT INDEX");
  const settingsPath = projectId ? `/project/${encodeURIComponent(projectId)}/settings` : "/account";
  const isSettingsActive = location.pathname.endsWith("/settings");

  const styleSuggestions = stylesData?.suggestions ?? [];
  const activeStyle = stylesData?.active_index == null
    ? null
    : styleSuggestions.find((s) => s.index === stylesData.active_index) ?? null;
  const styleItemsTotal = styleSuggestions.length;
  const styleItemsDone = styleSuggestions.filter((s) => s.has_sample).length;

  const pipelineStages = useMemo<PipelineNavStage[]>(() => {
    return UI_STAGES.map((stage) => {
      if (stage.key === "shot-plan") {
        const shotPlan = getShotPlanSubStatus(status);
        return {
          key: "shot-plan",
          route: stage.route,
          label: stage.label.toUpperCase(),
          status: shotPlan.status,
          itemsDone: shotPlan.itemsDone,
          itemsTotal: shotPlan.itemsTotal,
          failedCount: shotPlan.failedCount,
          needsApproval: shotPlan.status === "awaiting_review",
          detail: shotPlan.detail,
        };
      }

      const backendStage = stage.backendStages[0];
      const info = status?.stages[backendStage];
      return {
        key: stage.key,
        route: stage.route,
        label: stage.label.toUpperCase(),
        status: info?.status ?? "pending",
        itemsDone: info?.items_done ?? 0,
        itemsTotal: info?.items_total ?? 0,
        failedCount: info?.items_failed.length ?? 0,
        needsApproval: info?.status === "awaiting_review",
      };
    });
  }, [status]);

  const activeStageRoute = pipelineStages.find((stage) =>
    location.pathname.endsWith(`/${stage.route}`),
  )?.route ?? (isSettingsActive ? "" : pipelineStages[0]?.route ?? "");

  const stageDetails = useMemo<Record<string, string>>(() => {
    const details: Record<string, string> = {};

    if (storyBible) {
      details.extract = [
        plural(storyBible.scenes.length, "scene"),
        plural(storyBible.characters.length, "character"),
        plural(storyBible.locations.length, "location"),
      ].join(" · ");
      details.cast = [
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
      details.adapt = [
        plural(screenplays.length, "scene"),
        plural(beatCount, "beat"),
      ].join(" · ");
    }

    if (panelSummaries?.length) {
      const panelCount = panelSummaries.reduce((sum, scene) => sum + scene.panel_count, 0);
      details["shot-plan"] = [
        plural(panelSummaries.length, "scene"),
        plural(panelCount, "panel"),
      ].join(" · ");
    }

    if (promptSummaries?.length) {
      const promptCount = promptSummaries.reduce((sum, scene) => sum + scene.prompt_count, 0);
      details.direct = plural(promptCount, "prompt");
    }

    const drawItemsTotal = status?.stages.draw?.items_total ?? 0;
    const drawAccepted = images?.filter((image) => image.status === "done").length ?? 0;
    const drawDenominator = Math.max(drawItemsTotal, images?.length ?? 0);
    if (drawDenominator > 0) {
      details.draw = `${drawAccepted}/${drawDenominator} generated`;
    }

    if (pages?.length) {
      const pagePanelCount = pages.reduce((sum, page) => sum + page.panel_count, 0);
      details.compose = [
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
    status,
    storyBible,
    styleItemsDone,
    styleItemsTotal,
  ]);

  const needsApproval = status
    ? STAGE_ORDER.find((stage) => status.stages[stage]?.status === "awaiting_review")
    : null;
  const brokenStage = useMemo(() => status
    ? STAGE_ORDER.find((s) => {
        const info = status.stages[s];
        if (!info) return false;
        return info.status === "failed"
          || (info.status === "complete" && (info.items_failed?.length ?? 0) > 0);
      })
    : undefined, [status]);
  const pendingStage = useMemo(() => status
    ? STAGE_ORDER.find((s) => {
        const st = status.stages[s]?.status;
        return !st || st === "pending";
      })
    : undefined, [status]);
  const nextAttentionStage = needsApproval ?? brokenStage ?? pendingStage;
  const styleNeedsSelection =
    !!projectId &&
    !status?.style_selected &&
    (status?.stages.extract?.status === "complete" || status?.stages.extract?.status === "awaiting_review");
  const isRunning = status?.is_running ?? false;

  // Determine which stage will actually run when the user clicks NEXT STAGE,
  // so we can show a credit estimate before they commit to the action.
  const nextRunStage = useMemo<StageName | undefined>(() => {
    if (!status || isRunning || !projectId) return undefined;
    if (
      nextAttentionStage &&
      (nextAttentionStage === "plan" || nextAttentionStage === "storyboard") &&
      shotPlanAction.kind !== "none"
    ) {
      return shotPlanAction.estimateStage;
    }
    // For approval stages, find the first pending stage after approval so we can
    // show the cost estimate upfront (including extract → style).
    if (needsApproval) {
      const idx = STAGE_ORDER.indexOf(needsApproval);
      return STAGE_ORDER.slice(idx + 1).find((s) => {
        const st = status.stages[s]?.status;
        return !st || st === "pending";
      });
    }
    // Rerun the root broken stage if one exists.
    if (brokenStage) return brokenStage;
    // Normal advance: first pending stage.
    return STAGE_ORDER.find((s) => {
      const st = status.stages[s]?.status;
      return !st || st === "pending";
    });
  }, [status, isRunning, projectId, nextAttentionStage, shotPlanAction, needsApproval, brokenStage]);

  const { data: nextStageEstimate } = useStageEstimate(projectId, nextRunStage);
  const { data: creditBalance } = useCreditBalance();
  const showInsufficient = useInsufficientCreditsStore((s) => s.show);
  const [showCostConfirm, setShowCostConfirm] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);

  const requiredCredits = nextStageEstimate?.reserved_credits ?? nextStageEstimate?.estimate_credits ?? 0;
  const balanceCredits = creditBalance?.balance_credits ?? 0;
  const proactiveInsufficient =
    !!nextRunStage && requiredCredits > 0 && balanceCredits < requiredCredits;

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
    if (isRunning) setRunError(null);
  }, [isRunning]);

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

  const stageActionLabel = useCallback(
    (stage: string | undefined) =>
      stage ? `Run ${getBackendStageUiLabel(stage as StageName)}` : "Run stage",
    [],
  );

  const handleRunError = useCallback(
    (err: unknown, fallback: string, retry?: () => void) => {
      if (
        maybeShowInsufficientCredits(err, {
          actionLabel: stageActionLabel(nextRunStage),
          onRetry: retry,
        })
      ) {
        setRunError(null);
        return;
      }
      setRunError(err instanceof Error ? err.message : fallback);
    },
    [nextRunStage, stageActionLabel],
  );

  function handleRun() {
    if (!projectId || !pendingStage) return;
    setRunError(null);
    clearEvents();
    runPipeline.mutate(
      { project: projectId, stage: pendingStage },
      {
        onSuccess: () => connect(projectId),
        onError: (e) => handleRunError(e, "Failed to start pipeline", handleRun),
      },
    );
  }

  function handleContinue() {
    if (!projectId || isRunning) return;
    setRunError(null);
    if (needsApproval === "style" && styleNeedsSelection) {
      navigate(`/project/${encodeURIComponent(projectId)}/styles`);
      return;
    }
    if (needsApproval) {
      approveStage.mutate(
        { project: projectId, stage: needsApproval },
        {
          onSuccess: () => {
            if (!pendingStage) return;
            // After approving extract → style stage, send the user to the
            // style room so they see samples generate live.
            if (pendingStage === "style") {
              navigate(`/project/${encodeURIComponent(projectId)}/styles`);
            }
            clearEvents();
            runPipeline.mutate(
              { project: projectId, stage: pendingStage },
              {
                onSuccess: () => connect(projectId),
                onError: (e) => handleRunError(e, "Failed to start pipeline", handleContinue),
              },
            );
          },
          onError: (e) => handleRunError(e, "Failed to approve stage", handleContinue),
        },
      );
      return;
    }
    if (styleNeedsSelection) {
      navigate(`/project/${encodeURIComponent(projectId)}/styles`);
      return;
    }

    // Find the earliest stage that needs attention — either failed outright
    // or "complete" with failed items (partial failure that blocks downstream).
    // Rerunning from the root cause is better than retrying the surface symptom.
    if (
      nextAttentionStage &&
      (nextAttentionStage === "plan" || nextAttentionStage === "storyboard") &&
      shotPlanAction.kind !== "none"
    ) {
      clearEvents();
      if (shotPlanAction.kind === "run") {
        runPipeline.mutate(
          { project: projectId, stage: shotPlanAction.backendStage },
          {
            onSuccess: () => connect(projectId),
            onError: (e) => handleRunError(e, "Failed to start pipeline", handleContinue),
          },
        );
      } else if (shotPlanAction.kind === "rerun") {
        runPipeline.mutate(
          { project: projectId, stage: shotPlanAction.backendStage, rerun: true },
          {
            onSuccess: () => connect(projectId),
            onError: (e) => handleRunError(e, "Failed to start pipeline", handleContinue),
          },
        );
      }
      return;
    }
    if (brokenStage) {
      clearEvents();
      runPipeline.mutate(
        { project: projectId, stage: brokenStage, rerun: true },
        {
          onSuccess: () => connect(projectId),
          onError: (e) => handleRunError(e, "Failed to start pipeline", handleContinue),
        },
      );
      return;
    }

    handleRun();
  }

  function handleContinueClick() {
    // Pure navigation cases (no work to run, no credits to spend).
    if (needsApproval === "style" && styleNeedsSelection) {
      handleContinue();
      return;
    }
    if (styleNeedsSelection && !needsApproval && !nextRunStage) {
      handleContinue();
      return;
    }
    if (proactiveInsufficient && nextStageEstimate) {
      showInsufficient({
        info: {
          balance_credits: balanceCredits,
          required_credits: requiredCredits,
          shortfall_credits: requiredCredits - balanceCredits,
          stage: nextRunStage ?? null,
          action: null,
          message: `Insufficient credits — ${balanceCredits} available, ${requiredCredits} required`,
        },
        actionLabel: stageActionLabel(nextRunStage),
        onRetry: handleContinue,
      });
      return;
    }
    if (nextStageEstimate && nextStageEstimate.estimate_credits > 0) {
      setShowCostConfirm(true);
      return;
    }
    handleContinue();
  }

  function continueButtonLabel() {
    if (isRunning) return t("RUNNING…");
    if (
      nextAttentionStage &&
      (nextAttentionStage === "plan" || nextAttentionStage === "storyboard") &&
      shotPlanAction.kind !== "none"
    ) {
      return shotPlanAction.label.toUpperCase();
    }
    if (needsApproval === "style" && styleNeedsSelection) return "PICK STYLE";
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
      "w-full border-l-[3px] px-5 py-2 text-left transition-colors xl:px-6 xl:py-3 2xl:py-5 min-[2200px]:border-l-[5px] min-[2200px]:px-9 min-[2200px]:py-7",
      isActive
        ? "border-narrator-gold bg-bristol/8"
        : "border-transparent hover:bg-bristol/5",
    );

    return (
      <button
        key={stage.key}
        type="button"
        onClick={() => projectId && navigate(`/project/${encodeURIComponent(projectId)}/${stage.route}`)}
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
        <div className="mt-1.5 h-[4px] bg-bristol/10 xl:mt-2 2xl:mt-2.5 min-[2200px]:mt-4 min-[2200px]:h-[6px]">
          <div
            className={cn("h-full transition-all duration-300", progressTone(stage))}
            style={{ width: `${progressWidth(stage)}%` }}
          />
        </div>
        <div
          data-stage-detail
          {...(isActive ? { "data-active": "" } : {})}
          className={cn(
            "mt-1 flex items-baseline justify-between gap-2 font-meta text-[0.62rem] tracking-[0.06em] 2xl:mt-2 2xl:text-[0.72rem] min-[2200px]:mt-3 min-[2200px]:text-[1rem]",
            compactStageDetails && !isActive && "hidden",
            isActive ? "text-bristol/62" : "text-bristol/42",
          )}
        >
          <span className="min-w-0 truncate">{detail}</span>
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
      {projectId && (
        <select
          aria-label={t("PIPELINE STAGE")}
          value={activeStageRoute}
          onChange={(event) => navigate(`/project/${encodeURIComponent(projectId)}/${event.target.value}`)}
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
      <aside className="hidden h-full w-[240px] shrink-0 flex-col bg-ink-black text-bristol md:flex xl:w-[270px] 2xl:w-[320px] min-[2200px]:w-[430px]">
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
          <nav ref={navRef} aria-label="Pipeline stages" className="h-full overflow-y-auto py-2 pb-4 xl:py-3 xl:pb-6 2xl:py-5 2xl:pb-8 min-[2200px]:py-8">
            {projectId ? pipelineStages.map((stage) => renderStageRow(stage)) : (
              <div className="px-4 py-4 font-meta text-[0.6rem] tracking-[0.14em] text-bristol/35">
                {t("NO PROJECT SELECTED")}
              </div>
            )}
          </nav>
        </div>

        <div className="border-t border-bristol/10">
          <Link
            to={settingsPath}
            className={cn(
              "flex w-full items-center gap-3 border-l-[3px] px-5 py-3 font-meta text-[0.62rem] tracking-[0.14em] transition-colors xl:px-6 2xl:text-[0.68rem] min-[2200px]:px-9 min-[2200px]:py-4 min-[2200px]:text-[0.9rem]",
              isSettingsActive
                ? "border-l-narrator-gold bg-bristol/8 text-bristol"
                : "border-transparent text-bristol/45 hover:bg-bristol/5 hover:text-bristol/70",
            )}
          >
            <span className="text-[0.48rem] 2xl:text-[0.52rem] min-[2200px]:text-[0.72rem]">⊙</span>
            {t("Settings")}
          </Link>
        </div>

        <div className="border-t border-bristol/10 p-4 2xl:p-5 min-[2200px]:p-7">
          {projectId && (
            <button
              type="button"
              onClick={handleContinueClick}
              disabled={isRunning || approveStage.isPending || runPipeline.isPending}
              className="flex min-h-13 w-full items-center justify-center gap-2 border-[2px] border-ink-black/80 bg-hero-red px-3 py-3 font-meta text-[0.72rem] tracking-[0.18em] text-bristol shadow-ink-sm transition-colors hover:bg-hero-red/90 disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none 2xl:min-h-14 2xl:text-[0.82rem] min-[2200px]:min-h-20 min-[2200px]:text-[1.15rem]"
            >
              {isRunning && <Icon name="loader" size={14} className="animate-spin" />}
              {continueButtonLabel()} {!isRunning && "→"}
            </button>
          )}
          <ConfirmDrawer
            open={showCostConfirm}
            title={`Start ${nextRunStage ? getBackendStageUiLabel(nextRunStage) : "stage"}?`}
            body="Credits will be reserved now and settled to actual usage once the stage completes. Any unused portion of the hold is released automatically."
            cost={nextStageEstimate}
            confirmLabel={continueButtonLabel().replace("APPROVE & ", "")}
            busy={approveStage.isPending || runPipeline.isPending}
            onConfirm={() => { setShowCostConfirm(false); handleContinue(); }}
            onClose={() => setShowCostConfirm(false)}
          />
          {runError && (
            <div className="mt-2 px-1 font-meta text-[0.56rem] tracking-[0.12em] text-hero-red/80 2xl:text-[0.62rem]" role="alert">
              {runError}
            </div>
          )}
          {!runError && projectId && nextStageEstimate && nextStageEstimate.estimate_credits > 0 && !isRunning && (
            <div className="mt-2 flex flex-col items-center gap-1 font-meta text-[0.56rem] tracking-[0.12em] text-bristol/45 2xl:text-[0.62rem]">
              <div className="flex items-center justify-center gap-1.5">
                <span className="text-narrator-gold/70">Est. {nextStageEstimate.estimate_credits.toLocaleString()}</span>
                {nextStageEstimate.reserved_credits > 0 && (
                  <span>· Reserves up to {nextStageEstimate.reserved_credits.toLocaleString()}</span>
                )}
              </div>
              {proactiveInsufficient && (
                <div className="mt-1 flex items-center gap-1.5 font-meta tracking-[0.1em] text-narrator-gold/85">
                  <span>◆</span>
                  <span>
                    Short by {(requiredCredits - balanceCredits).toLocaleString()} —
                    {" "}<span className="underline">top up to continue</span>
                  </span>
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}

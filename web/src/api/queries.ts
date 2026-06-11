import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listProjects, getProjectStatus, createProject, deleteProject, generateProjectCover, listShortStories, importStory } from "./projects";
import { runPipeline, approveStage, regenPanel, regenPanelWithInstruction, regenRef, regenRefWithInstruction, regenPlate, regenPlateWithInstruction, regenProp, regenPropWithInstruction, getGenerationJobs, regenExtract, resetStale, fetchStageEstimate, fetchRegenEstimate } from "./pipeline";
import type { ConfigOverrides, StoryBible, ProjectStatus, StageInfo } from "../types/api";
import { reconcileStatusPoll } from "../lib/stageProgress";
import { getBalance, getCreditHistory, getPricingReference } from "./credits";
import { getPackages, createCheckout } from "./billing";
import {
  getStoryBible,
  updateStoryBible,
  listScreenplays,
  getScreenplay,
  getLayoutPlan,
  estimateNarrationDecisionImpact,
  updateNarrationDecision,
  listPanelSummaries,
  getPanelsForScene,
  updatePanel,
  listPromptSummaries,
  getPromptsForScene,
  updatePrompt,
  listImages,
  getImageGenerationMeta,
  getPanelImageVersions,
  restorePanelImageVersion,
  acceptImagePanel,
  unacceptImagePanel,
} from "./stages";
import { listPages, getPage, updatePage, replacePage, generatePageStyleVars, translatePageBubbles, setTheme, translateSinglePageBubbles, triggerExport } from "./pages";
import { getStyles, suggestStyles, fetchSuggestStylesEstimate, generateStyleSamples, setActiveStyle } from "./styles";
import { getProjectConfig, updateProjectConfig } from "./config";
import {
  listLabsModels,
  getDefaultFixture,
  listImportableProjects,
  listProjectScenes,
  importProjectScene,
  createLabsRun,
  deleteLabsRun,
  listLabsRuns,
  getLabsRun,
  type LabsRunCreatePayload,
  type LabsRunDetail,
} from "./labs";

// ── Projects ──────────────────────────────────────────────────────────────────

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });
}

export function useProjectStatus(name: string | undefined) {
  const qc = useQueryClient();
  const query = useQuery({
    queryKey: ["project", name, "status"],
    queryFn: async () => {
      const fresh = await getProjectStatus(name!);
      const cached = qc.getQueryData<ProjectStatus>(["project", name, "status"]);
      return reconcileStatusPoll(cached, fresh);
    },
    enabled: !!name,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data?.is_running ? 2000 : false;
    },
  });
  return query;
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ file, name, configOverrides }: { file: File; name: string; configOverrides?: Partial<ConfigOverrides> }) =>
      createProject(file, name, configOverrides),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useShortStories() {
  return useQuery({
    queryKey: ["short-stories"],
    queryFn: listShortStories,
    staleTime: 60_000 * 5,
  });
}

export function useImportStory() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ name, urlOrCode, configOverrides }: { name: string; urlOrCode: string; configOverrides?: Partial<ConfigOverrides> }) =>
      importStory(name, urlOrCode, configOverrides),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}


export function useGenerateProjectCover() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project }: { project: string }) => generateProjectCover(project),
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string }) => deleteProject(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useProjectConfig(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "config"],
    queryFn: () => getProjectConfig(project!),
    enabled: !!project,
  });
}

export function useUpdateProjectConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, data }: { project: string; data: Parameters<typeof updateProjectConfig>[1] }) =>
      updateProjectConfig(project, data),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "config"] });
    },
  });
}

// ── Pipeline ──────────────────────────────────────────────────────────────────

// Optimistically mark a stage as running in the cached project status so any
// room the user navigates to next sees `running` on first render — that lets
// RoomShell render the rich StageRunning placeholder (badge + progress) instead
// of the basic LoadingBlock spinner during the post-kickoff fetch race.
function markStageRunningInCache(
  qc: ReturnType<typeof useQueryClient>,
  project: string,
  stage: string,
): ProjectStatus | undefined {
  const key = ["project", project, "status"] as const;
  const previous = qc.getQueryData<ProjectStatus>(key);
  if (!previous) return previous;
  const existing: StageInfo | undefined = previous.stages[stage];
  const next: StageInfo = {
    status: "running",
    items_done: existing?.items_done ?? 0,
    items_total: existing?.items_total ?? 0,
    items_failed: existing?.items_failed ?? [],
    cost_credits: existing?.cost_credits ?? 0,
    estimated_cost_credits: existing?.estimated_cost_credits ?? 0,
    error: null,
    started_at: existing?.started_at ?? null,
    finished_at: null,
    last_progress_at: existing?.last_progress_at ?? null,
    stale: false,
    in_flight: existing?.in_flight ?? [],
  };
  qc.setQueryData<ProjectStatus>(key, {
    ...previous,
    is_running: true,
    stages: { ...previous.stages, [stage]: next },
  });
  return previous;
}

export function useRunPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, stage, rerun, retryFailed }: { project: string; stage?: string; rerun?: boolean; retryFailed?: boolean }) =>
      runPipeline(project, stage, rerun, retryFailed),
    onMutate: async ({ project, stage }) => {
      if (!stage) return { previous: undefined };
      // Cancel in-flight refetches so they can't clobber our optimistic write.
      await qc.cancelQueries({ queryKey: ["project", project, "status"] });
      const previous = markStageRunningInCache(qc, project, stage);
      return { previous };
    },
    onError: (_err, { project }, context) => {
      if (context?.previous) {
        qc.setQueryData(["project", project, "status"], context.previous);
      }
    },
    onSettled: (_data, _err, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useApproveStage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      project,
      stage,
    }: {
      project: string;
      stage: string;
    }) => approveStage(project, stage),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useRegenPanel() {
  return useMutation({
    mutationFn: ({
      project,
      sceneId,
      panelNumber,
      imageModelAlias,
    }: {
      project: string;
      sceneId: string;
      panelNumber: number;
      imageModelAlias?: string | null;
    }) => regenPanel(project, sceneId, panelNumber, imageModelAlias),
    // No cache invalidation here — DrawRoom detects completion via images polling
    // and busts the cache itself to avoid the panel disappearing mid-regen.
  });
}

export function useRegenPanelWithInstruction() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      project,
      sceneId,
      panelNumber,
      instruction,
      imageModelAlias,
    }: {
      project: string;
      sceneId: string;
      panelNumber: number;
      instruction: string;
      imageModelAlias?: string | null;
    }) => regenPanelWithInstruction(project, sceneId, panelNumber, instruction, imageModelAlias),
    onSuccess: (data, { project, sceneId }) => {
      qc.setQueryData<import("../types/api").ImagePrompt[]>(
        ["project", project, "direct", sceneId],
        (existing) => existing?.map((prompt) =>
          prompt.panel_number === data.panel_number ? data.prompt : prompt
        ),
      );
      qc.invalidateQueries({ queryKey: ["project", project, "direct", sceneId] });
    },
  });
}

export function useStageEstimate(project: string | undefined, stage: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "estimate", stage],
    queryFn: () => fetchStageEstimate(project!, stage!),
    enabled: !!project && !!stage && enabled,
    staleTime: 60_000,
  });
}

export function useRegenEstimate(
  project: string | undefined,
  sceneId: string | undefined,
  panelNumber: number | undefined,
  imageModelAlias?: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: ["project", project, "regen-estimate", sceneId, panelNumber, imageModelAlias ?? ""],
    queryFn: () => fetchRegenEstimate(project!, sceneId!, panelNumber!, imageModelAlias),
    enabled: !!project && !!sceneId && panelNumber != null && enabled,
    staleTime: 60_000,
  });
}

export function useNarrationDecisionImpact(
  project: string | undefined,
  beatId: string | undefined,
  patch: Partial<import("../types/api").NarrationDecision> | null,
  enabled = true,
) {
  return useQuery({
    queryKey: ["project", project, "narration-impact", beatId, patch],
    queryFn: () => estimateNarrationDecisionImpact(project!, beatId!, patch ?? {}),
    enabled: !!project && !!beatId && !!patch && enabled,
    staleTime: 15_000,
  });
}

export function useUpdateNarrationDecision() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      project,
      beatId,
      patch,
    }: {
      project: string;
      beatId: string;
      patch: Partial<import("../types/api").NarrationDecision>;
    }) => updateNarrationDecision(project, beatId, patch),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "plan"] });
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
    },
  });
}

export function useRegenExtract() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project }: { project: string }) =>
      regenExtract(project),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
      qc.invalidateQueries({ queryKey: ["project", project, "story-bible"] });
    },
  });
}

export function useResetStale() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project }: { project: string }) => resetStale(project),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useRegenRef() {
  return useMutation({
    mutationFn: ({ project, charId }: { project: string; charId: string }) =>
      regenRef(project, charId),
  });
}

export function useRegenRefWithInstruction() {
  return useMutation({
    mutationFn: ({
      project,
      charId,
      instruction,
    }: {
      project: string;
      charId: string;
      instruction: string;
    }) => regenRefWithInstruction(project, charId, instruction),
  });
}

export function useRegenPlate() {
  return useMutation({
    mutationFn: ({ project, locId }: { project: string; locId: string }) =>
      regenPlate(project, locId),
  });
}

export function useRegenPlateWithInstruction() {
  return useMutation({
    mutationFn: ({
      project,
      locId,
      instruction,
    }: {
      project: string;
      locId: string;
      instruction: string;
    }) => regenPlateWithInstruction(project, locId, instruction),
  });
}

export function useRegenProp() {
  return useMutation({
    mutationFn: ({ project, propId }: { project: string; propId: string }) =>
      regenProp(project, propId),
  });
}

export function useRegenPropWithInstruction() {
  return useMutation({
    mutationFn: ({
      project,
      propId,
      instruction,
    }: {
      project: string;
      propId: string;
      instruction: string;
    }) => regenPropWithInstruction(project, propId, instruction),
  });
}

export function useGenerationJobs(project: string | undefined, ids: string[]) {
  return useQuery({
    queryKey: ["project", project, "generation-jobs", ids],
    queryFn: () => getGenerationJobs(project!, ids),
    enabled: !!project && ids.length > 0,
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs ?? [];
      return jobs.some((job) => job.status === "queued" || job.status === "running")
        ? 1000
        : false;
    },
  });
}

// ── Story Bible (EXTRACT) ─────────────────────────────────────────────────────

export function useStoryBible(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "story-bible"],
    queryFn: () => getStoryBible(project!),
    enabled: !!project && enabled,
  });
}

export function useUpdateStoryBible() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, data }: { project: string; data: StoryBible }) =>
      updateStoryBible(project, data),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "story-bible"] });
    },
  });
}

// ── Screenplays (ADAPT) ───────────────────────────────────────────────────────

export function useScreenplays(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "screenplays"],
    queryFn: () => listScreenplays(project!),
    enabled: !!project,
  });
}

export function useScreenplay(
  project: string | undefined,
  sceneId: string | null | undefined,
) {
  return useQuery({
    queryKey: ["project", project, "screenplays", sceneId],
    queryFn: () => getScreenplay(project!, sceneId!),
    enabled: !!project && !!sceneId,
  });
}

export function useLayoutPlan(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "plan"],
    queryFn: () => getLayoutPlan(project!),
    enabled: !!project,
  });
}

// ── Panels (STORYBOARD) ───────────────────────────────────────────────────────

export function usePanelSummaries(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "storyboard"],
    queryFn: () => listPanelSummaries(project!),
    enabled: !!project,
  });
}

export function usePanelsForScene(
  project: string | undefined,
  sceneId: string | null | undefined,
) {
  return useQuery({
    queryKey: ["project", project, "storyboard", sceneId],
    queryFn: () => getPanelsForScene(project!, sceneId!),
    enabled: !!project && !!sceneId,
  });
}

export function useUpdatePanel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, sceneId, data }: { project: string; sceneId: string; data: import("../types/api").PanelBreakdown }) =>
      updatePanel(project, sceneId, data.panel_number, data),
    onSuccess: (_data, { project, sceneId }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "storyboard", sceneId] });
    },
  });
}

// ── Prompts (DIRECT) ──────────────────────────────────────────────────────────

export function usePromptSummaries(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "direct"],
    queryFn: () => listPromptSummaries(project!),
    enabled: !!project,
  });
}

export function usePromptsForScene(
  project: string | undefined,
  sceneId: string | null | undefined,
) {
  return useQuery({
    queryKey: ["project", project, "direct", sceneId],
    queryFn: () => getPromptsForScene(project!, sceneId!),
    enabled: !!project && !!sceneId,
  });
}

export function useUpdatePrompt() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, sceneId, data }: { project: string; sceneId: string; data: import("../types/api").ImagePrompt }) =>
      updatePrompt(project, sceneId, data.panel_number, data),
    onSuccess: (_data, { project, sceneId }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "direct", sceneId] });
    },
  });
}

export function useImageGenerationMeta(
  project: string | undefined,
  relativeImagePath: string | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: ["project", project, "image-generation-meta", relativeImagePath],
    queryFn: () => getImageGenerationMeta(project!, relativeImagePath!),
    enabled: !!project && !!relativeImagePath && enabled,
  });
}

export function usePanelImageVersions(
  project: string | undefined,
  sceneId: string | undefined,
  panelNumber: number | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: ["project", project, "panel-image-versions", sceneId, panelNumber],
    queryFn: () => getPanelImageVersions(project!, sceneId!, panelNumber!),
    enabled: !!project && !!sceneId && !!panelNumber && enabled,
    retry: false,
  });
}

export function useRestorePanelImageVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      project,
      sceneId,
      panelNumber,
      version,
    }: {
      project: string;
      sceneId: string;
      panelNumber: number;
      version: number;
    }) => restorePanelImageVersion(project, sceneId, panelNumber, version),
    onSuccess: (_data, { project, sceneId, panelNumber }) => {
      const panelRelPath = `draw/${sceneId}/panel_${String(panelNumber).padStart(3, "0")}.png`;
      qc.invalidateQueries({ queryKey: ["project", project, "draw"] });
      qc.invalidateQueries({ queryKey: ["project", project, "image-generation-meta", panelRelPath] });
      qc.invalidateQueries({ queryKey: ["project", project, "panel-image-versions", sceneId, panelNumber] });
    },
  });
}

// ── Images (DRAW) ─────────────────────────────────────────────────────────────

export function useImages(project: string | undefined, refetchInterval?: number) {
  return useQuery({
    queryKey: ["project", project, "draw"],
    queryFn: () => listImages(project!),
    enabled: !!project,
    refetchInterval,
  });
}

export function useAcceptPanel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, sceneId, panelNumber }: { project: string; sceneId: string; panelNumber: number }) =>
      acceptImagePanel(project, sceneId, panelNumber),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "draw"] });
    },
  });
}

export function useUnacceptPanel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, sceneId, panelNumber }: { project: string; sceneId: string; panelNumber: number }) =>
      unacceptImagePanel(project, sceneId, panelNumber),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "draw"] });
    },
  });
}

// ── Pages (COMPOSE) ───────────────────────────────────────────────────────────

export function usePages(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "pages"],
    queryFn: () => listPages(project!),
    enabled: !!project,
  });
}

export function usePage(project: string | undefined, pageNum: number | undefined) {
  return useQuery({
    queryKey: ["project", project, "pages", pageNum],
    queryFn: () => getPage(project!, pageNum!),
    enabled: !!project && !!pageNum,
  });
}

export function useUpdatePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, pageNum, data }: { project: string; pageNum: number; data: Partial<import("../types/api").ComicPage> }) =>
      updatePage(project, pageNum, data),
    onSuccess: (data, { project, pageNum }) => {
      // Populate the specific page cache directly — avoids the refetch that causes
      // the rubber-band snap when dragging bubbles.
      qc.setQueryData(["project", project, "pages", pageNum], data);
      // Only invalidate the summary list (exact match skips the per-page query).
      qc.invalidateQueries({ queryKey: ["project", project, "pages"], exact: true });
    },
  });
}

export function useReplacePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, pageNum, data }: { project: string; pageNum: number; data: import("../types/api").ComicPage }) =>
      replacePage(project, pageNum, data),
    onSuccess: (_data, { project, pageNum }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "pages", pageNum] });
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
    },
  });
}

export function useGeneratePageStyleVars() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project }: { project: string }) => generatePageStyleVars(project),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
    },
  });
}

export function useTranslatePageBubbles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, targetLanguage }: { project: string; targetLanguage?: "en" | "es" | "fr" }) =>
      translatePageBubbles(project, targetLanguage),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
      qc.invalidateQueries({ queryKey: ["project", project, "config"] });
    },
  });
}

export function useSetTheme() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, theme }: { project: string; theme: string }) =>
      setTheme(project, theme),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
    },
  });
}

export function useTranslateSinglePageBubbles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, pageNum, targetLanguage }: { project: string; pageNum: number; targetLanguage?: "en" | "es" | "fr" }) =>
      translateSinglePageBubbles(project, pageNum, targetLanguage),
    onSuccess: (_data, { project, pageNum }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "pages", pageNum] });
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
    },
  });
}

export function useExport() {
  return useMutation({
    mutationFn: ({ project, format }: { project: string; format: "pdf" | "cbz" }) =>
      triggerExport(project, format),
  });
}

// ── Styles ───────────────────────────────────────────────────────────────────

export function useStyles(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "styles"],
    queryFn: () => getStyles(project!),
    enabled: !!project,
  });
}

export function useSuggestStyles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project }: { project: string }) => suggestStyles(project),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "styles"] });
    },
  });
}

export function useSuggestStylesEstimate(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "styles", "suggest-estimate"],
    queryFn: () => fetchSuggestStylesEstimate(project!),
    enabled: !!project && enabled,
    staleTime: 60_000,
  });
}

export function useGenerateStyleSamples() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, indices }: { project: string; indices: number[] }) =>
      generateStyleSamples(project, indices),
    onSettled: (_data, _error, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "styles"] });
    },
  });
}

export function useSetActiveStyle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, index }: { project: string; index: number }) =>
      setActiveStyle(project, index),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "styles"] });
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
    },
  });
}

// ── Credits & Billing ─────────────────────────────────────────────────────────

export function useCreditBalance() {
  return useQuery({
    queryKey: ["credits", "balance"],
    queryFn: getBalance,
    // Stay fresh-ish but pick up Stripe webhook deposits when the user
    // returns to the tab from Checkout.
    staleTime: 15_000,
    refetchOnWindowFocus: true,
  });
}

export function usePricingReference() {
  return useQuery({
    queryKey: ["credits", "pricing-reference"],
    queryFn: getPricingReference,
    staleTime: Infinity,
  });
}

export function useCreditHistory() {
  return useQuery({
    queryKey: ["credits", "history"],
    queryFn: getCreditHistory,
  });
}

export function useCreditPackages() {
  return useQuery({
    queryKey: ["billing", "packages"],
    queryFn: getPackages,
    staleTime: Infinity,
  });
}

export function useCreateCheckout() {
  return useMutation({
    mutationFn: ({ packageId }: { packageId: string }) => createCheckout(packageId),
    onSuccess: ({ url }) => {
      window.location.href = url;
    },
  });
}

// ── Labs ──────────────────────────────────────────────────────────────────────

export function useLabsModels() {
  return useQuery({
    queryKey: ["labs", "models"],
    queryFn: listLabsModels,
    staleTime: 0,
  });
}

export function useLabsFixture() {
  return useQuery({
    queryKey: ["labs", "fixtures", "default"],
    queryFn: getDefaultFixture,
    staleTime: Infinity,
  });
}

export function useLabsImportableProjects() {
  return useQuery({
    queryKey: ["labs", "projects"],
    queryFn: listImportableProjects,
  });
}

export function useLabsProjectScenes(projectId: string | undefined) {
  return useQuery({
    queryKey: ["labs", "projects", projectId, "scenes"],
    queryFn: () => listProjectScenes(projectId!),
    enabled: !!projectId,
  });
}

export function useImportLabsScene() {
  return useMutation({
    mutationFn: ({ projectId, sceneId, panelLimit }: { projectId: string; sceneId: string; panelLimit?: number }) =>
      importProjectScene(projectId, { scene_id: sceneId, panel_limit: panelLimit ?? 8 }),
  });
}

export function useCreateLabsRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: LabsRunCreatePayload) => createLabsRun(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["labs", "runs"] });
    },
  });
}

export function useDeleteLabsRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) => deleteLabsRun(runId),
    onSuccess: (_data, runId) => {
      qc.removeQueries({ queryKey: ["labs", "runs", runId] });
      qc.invalidateQueries({ queryKey: ["labs", "runs"] });
    },
  });
}

export function useLabsRuns() {
  return useQuery({
    queryKey: ["labs", "runs"],
    queryFn: listLabsRuns,
  });
}

export function useLabsRun(runId: string | undefined) {
  return useQuery<LabsRunDetail>({
    queryKey: ["labs", "runs", runId],
    queryFn: () => getLabsRun(runId!),
    enabled: !!runId,
    refetchInterval: (query) => {
      const data = query.state.data;
      return data && data.status === "running" ? 1500 : false;
    },
  });
}

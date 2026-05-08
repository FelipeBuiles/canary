import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listProjects, getProjectStatus, createProject, deleteProject, generateProjectCover } from "./projects";
import { runPipeline, approveStage, regenPanel, regenPanelWithInstruction, regenRef, regenPlate, getGenerationJobs, regenExtract, resetStale, fetchStageEstimate, fetchRegenEstimate } from "./pipeline";
import type { ConfigOverrides, StoryBible, CharacterVoice } from "../types/api";
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
import { listPages, getPage, updatePage, replacePage, reflowPages, generatePageStyleVars, translatePageBubbles, setTheme, applyBubblePreset, getBubblePresets, translateSinglePageBubbles, getCharacterVoices, putCharacterVoice, deleteCharacterVoice, reflowSinglePage, triggerExport, applyStructuralOperation } from "./pages";
import { getStyles, suggestStyles, generateStyleSamples, setActiveStyle } from "./styles";
import { getProjectConfig, updateProjectConfig } from "./config";

// ── Projects ──────────────────────────────────────────────────────────────────

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });
}

export function useProjectStatus(name: string | undefined) {
  const query = useQuery({
    queryKey: ["project", name, "status"],
    queryFn: () => getProjectStatus(name!),
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

export function useRunPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, stage, rerun }: { project: string; stage?: string; rerun?: boolean }) =>
      runPipeline(project, stage, rerun),
    onSuccess: (_data, { project }) => {
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
    mutationFn: ({ project, sceneId, panelNumber }: { project: string; sceneId: string; panelNumber: number }) =>
      regenPanel(project, sceneId, panelNumber),
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
    }: {
      project: string;
      sceneId: string;
      panelNumber: number;
      instruction: string;
    }) => regenPanelWithInstruction(project, sceneId, panelNumber, instruction),
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
  enabled = true,
) {
  return useQuery({
    queryKey: ["project", project, "regen-estimate", sceneId, panelNumber],
    queryFn: () => fetchRegenEstimate(project!, sceneId!, panelNumber!),
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

export function useRegenPlate() {
  return useMutation({
    mutationFn: ({ project, locId }: { project: string; locId: string }) =>
      regenPlate(project, locId),
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

export function useReflowPages() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, panelsPerPage }: { project: string; panelsPerPage: number }) =>
      reflowPages(project, panelsPerPage),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
      qc.invalidateQueries({ queryKey: ["project", project, "plan"] });
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

export function useBubblePresets(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "bubble-presets"],
    queryFn: () => getBubblePresets(project!),
    enabled: !!project,
  });
}

export function useApplyBubblePreset() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, presetName }: { project: string; presetName: string }) =>
      applyBubblePreset(project, presetName),
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

export function useCharacterVoices(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "character-voices"],
    queryFn: () => getCharacterVoices(project!),
    enabled: !!project,
  });
}

export function usePutCharacterVoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, voice }: { project: string; voice: CharacterVoice }) =>
      putCharacterVoice(project, voice),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "character-voices"] });
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
    },
  });
}

export function useDeleteCharacterVoice() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, characterId }: { project: string; characterId: string }) =>
      deleteCharacterVoice(project, characterId),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "character-voices"] });
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
    },
  });
}

export function useReflowSinglePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, pageNum, layoutPreset }: { project: string; pageNum: number; layoutPreset: string }) =>
      reflowSinglePage(project, pageNum, layoutPreset),
    onSuccess: (data, { project, pageNum }) => {
      qc.setQueryData(["project", project, "pages", pageNum], data);
      qc.setQueriesData(
        { queryKey: ["project", project, "pages"] },
        (existing: import("../types/api").PageSummary[] | undefined) =>
          existing?.map((summary) =>
            summary.page_number === pageNum
              ? {
                  ...summary,
                  panel_count: data.panels.length,
                  layout: data.layout,
                  theme: data.theme,
                }
              : summary,
          ) ?? existing,
      );
      qc.invalidateQueries({ queryKey: ["project", project, "pages", pageNum] });
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
      qc.invalidateQueries({ queryKey: ["project", project, "plan"] });
    },
  });
}

export function useApplyStructuralOperation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, data }: { project: string; data: Record<string, unknown> }) =>
      applyStructuralOperation(project, data),
    onSuccess: (data, { project }) => {
      if (data.page) {
        qc.setQueryData(["project", project, "pages", data.page.page_number], data.page);
      }
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
      qc.invalidateQueries({ queryKey: ["project", project, "plan"] });
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

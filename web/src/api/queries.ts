import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listProjects, getProjectStatus, createProject, generateProjectCover } from "./projects";
import { runPipeline, approveStage, regenPanel, regenRef, regenPlate, getGenerationJobs } from "./pipeline";
import type { ConfigOverrides, StoryBible } from "../types/api";
import {
  getStoryBible,
  updateStoryBible,
  listScreenplays,
  getScreenplay,
  listPanelSummaries,
  getPanelsForScene,
  updatePanel,
  listPromptSummaries,
  getPromptsForScene,
  updatePrompt,
  listImages,
} from "./stages";
import { listPages, getPage, updatePage, replacePage, reflowPages, generatePageStyleVars, translatePageBubbles, triggerExport } from "./pages";
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
    mutationFn: ({ project, stage }: { project: string; stage?: string }) =>
      runPipeline(project, stage),
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

export function useStoryBible(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "story-bible"],
    queryFn: () => getStoryBible(project!),
    enabled: !!project,
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

// ── Panels (STORYBOARD) ───────────────────────────────────────────────────────

export function usePanelSummaries(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "panels"],
    queryFn: () => listPanelSummaries(project!),
    enabled: !!project,
  });
}

export function usePanelsForScene(
  project: string | undefined,
  sceneId: string | null | undefined,
) {
  return useQuery({
    queryKey: ["project", project, "panels", sceneId],
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
      qc.invalidateQueries({ queryKey: ["project", project, "panels", sceneId] });
    },
  });
}

// ── Prompts (DIRECT) ──────────────────────────────────────────────────────────

export function usePromptSummaries(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "prompts"],
    queryFn: () => listPromptSummaries(project!),
    enabled: !!project,
  });
}

export function usePromptsForScene(
  project: string | undefined,
  sceneId: string | null | undefined,
) {
  return useQuery({
    queryKey: ["project", project, "prompts", sceneId],
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
      qc.invalidateQueries({ queryKey: ["project", project, "prompts", sceneId] });
    },
  });
}

// ── Images (DRAW) ─────────────────────────────────────────────────────────────

export function useImages(project: string | undefined, refetchInterval?: number) {
  return useQuery({
    queryKey: ["project", project, "images"],
    queryFn: () => listImages(project!),
    enabled: !!project,
    refetchInterval,
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
    onSuccess: (_data, { project, pageNum }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "pages", pageNum] });
      qc.invalidateQueries({ queryKey: ["project", project, "pages"] });
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
    },
  });
}

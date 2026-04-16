import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { listProjects, getProjectStatus } from "./projects";
import { runPipeline, approveStage, regenPanel } from "./pipeline";
import {
  getStoryBible,
  listScreenplays,
  getScreenplay,
  listPanelSummaries,
  getPanelsForScene,
  listPromptSummaries,
  getPromptsForScene,
  listImages,
} from "./stages";
import { listPages, getPage } from "./pages";

// ── Projects ──────────────────────────────────────────────────────────────────

export function useProjects() {
  return useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });
}

export function useProjectStatus(name: string | undefined) {
  return useQuery({
    queryKey: ["project", name, "status"],
    queryFn: () => getProjectStatus(name!),
    enabled: !!name,
    refetchInterval: 5000,
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

// ── Story Bible (EXTRACT) ─────────────────────────────────────────────────────

export function useStoryBible(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "story-bible"],
    queryFn: () => getStoryBible(project!),
    enabled: !!project,
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

import type { CastReferenceInput } from "../types/api";
import { useInfiniteQuery, useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { isNotFoundError } from "./client";
import { listProjects, getProjectStatus, createProject, renameProject, deleteProject, fetchProjectCoverEstimate, generateProjectCover, listShortStories, importStory } from "./projects";
import { runPipeline, approveStage, regenRef, regenStateRef, regenLocationState, regenRefWithInstruction, regenPlate, regenPlateWithInstruction, regenProp, regenPropWithInstruction, getGenerationJobs, regenExtract, resetStale, fetchStageEstimate, fetchAssetRegenEstimate, getCastAssetVersions, restoreCastAssetVersion } from "./pipeline";
import type { AdaptationBrief, ConfigOverrides, StoryBible, ProjectStatus, ProjectSummary } from "../types/api";
import { reconcileStatusPoll } from "../lib/stageProgress";
import { getBalance, getCreditHistory, getPricingReference } from "./credits";
import { getPackages, createCheckout } from "./billing";
import {
  getStoryBible,
  getStory,
  updateBrief,
  updateStoryBible,
  getImageGenerationMeta,
  getPrimaryRefs,
  setPrimaryRef,
} from "./stages";
import {
  acceptPageIssue,
  analyzeCompletePage,
  getProviderUsage,
  dismissPageIssue,
  generateCompletePage,
  getAdaptation,
  getBookPlan,
  getStageValidation,
  getCompletePage,
  getCompletePageEstimate,
  getPageAnalysisEstimate,
  getCompletePageBatchEstimate,
  listCompletePages,
  getFinishPreflight,
  runFinishPreflight,
  triggerExport,
} from "./pages";
import { createStyleDirection, generateStyleValidation, getStyles, suggestStyles, fetchStyleDirectionEstimate, fetchSuggestStylesEstimate, fetchStyleSampleEstimate, generateStyleSamples, setActiveStyle } from "./styles";
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
    refetchInterval: (query) => {
      const projects = query.state.data;
      return projects?.some((project) =>
        project.cover_job?.status === "queued" || project.cover_job?.status === "running"
      ) ? 3000 : false;
    },
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
    refetchOnWindowFocus: "always",
    refetchOnMount: "always",
    refetchInterval: (query) => {
      if (isNotFoundError(query.state.error)) return false;
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

export function useProjectCoverEstimate(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "cover-estimate"],
    queryFn: () => fetchProjectCoverEstimate(project!),
    enabled: !!project && enabled,
    staleTime: 60_000,
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id }: { id: string }) => deleteProject(id),
    onSuccess: (_data, { id }) => {
      qc.removeQueries({ queryKey: ["project", id] });
      qc.invalidateQueries({ queryKey: ["projects"] });
    },
  });
}

export function useRenameProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameProject(id, name),
    onSuccess: async (data, { id }) => {
      const projectsKey = ["projects"];
      const statusKey = ["project", id, "status"];
      await Promise.all([
        qc.cancelQueries({ queryKey: projectsKey, exact: true }),
        qc.cancelQueries({ queryKey: statusKey, exact: true }),
      ]);
      qc.setQueryData<ProjectSummary[]>(projectsKey, (projects) => projects?.map((project) =>
        project.id === id ? { ...project, project_name: data.project_name } : project
      ));
      qc.setQueryData<ProjectStatus>(statusKey, (status) =>
        status ? { ...status, project_name: data.project_name } : status
      );
      await Promise.all([
        qc.invalidateQueries({ queryKey: projectsKey, exact: true }),
        qc.invalidateQueries({ queryKey: statusKey, exact: true }),
      ]);
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
    onSuccess: async (data, { project }) => {
      qc.setQueryData(["project", project, "config"], data);
      await qc.invalidateQueries({ queryKey: ["project", project] });
    },
  });
}

// ── Pipeline ──────────────────────────────────────────────────────────────────

export function useRunPipeline() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, stage, rerun, retryFailed, queuePages }: { project: string; stage?: string; rerun?: boolean; retryFailed?: boolean; queuePages?: boolean }) =>
      runPipeline(project, stage, rerun, retryFailed, queuePages),
    // Admission can fail before any work starts. Keep the initiating component
    // mounted so its pending state and rejection remain visible; only server
    // status/SSE may switch the room to running.
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

export function useStageEstimate(project: string | undefined, stage: string | undefined, enabled = true, rerun = false) {
  return useQuery({
    queryKey: ["project", project, "estimate", stage, ...(rerun ? ["restart"] : [])],
    queryFn: () => fetchStageEstimate(project!, stage!, rerun),
    enabled: !!project && !!stage && enabled,
    staleTime: 60_000,
  });
}

export function useAssetRegenEstimate(
  project: string | undefined,
  assetType: "character" | "location" | "prop",
  assetId: string | undefined,
  stateId?: string,
  enabled = true,
  referenceCount?: number,
) {
  return useQuery({
    queryKey: ["project", project, "asset-regen-estimate", assetType, assetId, stateId ?? "", referenceCount],
    queryFn: () => fetchAssetRegenEstimate(project!, assetType, assetId!, stateId, referenceCount),
    enabled: !!project && !!assetId && enabled,
    staleTime: 60_000,
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

export function useRegenStateRef() {
  return useMutation({
    mutationFn: ({ project, charId, stateId }: { project: string; charId: string; stateId: string }) =>
      regenStateRef(project, charId, stateId),
  });
}

export function useRegenLocationState() {
  return useMutation({
    mutationFn: ({ project, locId, stateId }: { project: string; locId: string; stateId: string }) =>
      regenLocationState(project, locId, stateId),
  });
}

export function useRegenRefWithInstruction() {
  return useMutation({
    mutationKey: ["reference-instruction", "char_id"],
    mutationFn: ({
      project,
      charId,
      instruction,
      referenceAssets,
      stateId,
    }: {
      project: string;
      charId: string;
      instruction: string;
      referenceAssets?: CastReferenceInput[];
      stateId?: string;
    }) => regenRefWithInstruction(project, charId, instruction, referenceAssets, stateId),
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
    mutationKey: ["reference-instruction", "loc_id"],
    mutationFn: ({
      project,
      locId,
      instruction,
      referenceAssets,
      stateId,
    }: {
      project: string;
      locId: string;
      instruction: string;
      referenceAssets?: CastReferenceInput[];
      stateId?: string;
    }) => regenPlateWithInstruction(project, locId, instruction, referenceAssets, stateId),
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
    mutationKey: ["reference-instruction", "prop_id"],
    mutationFn: ({
      project,
      propId,
      instruction,
      referenceAssets,
      stateId,
    }: {
      project: string;
      propId: string;
      instruction: string;
      referenceAssets?: CastReferenceInput[];
      stateId?: string;
    }) => regenPropWithInstruction(project, propId, instruction, referenceAssets, stateId),
  });
}

export function useGenerationJobs(
  project: string | undefined,
  ids: string[],
  watchAll = false,
) {
  return useQuery({
    queryKey: ["project", project, "generation-jobs", ids],
    queryFn: () => getGenerationJobs(project!, ids),
    enabled: !!project && (ids.length > 0 || watchAll),
    refetchInterval: (query) => {
      const jobs = query.state.data?.jobs ?? [];
      return jobs.some((job) => job.status === "queued" || job.status === "running")
        ? 1000
        : watchAll ? 15_000 : false;
    },
  });
}

// ── Story Bible (EXTRACT) ─────────────────────────────────────────────────────

export function useStory(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "story"],
    queryFn: () => getStory(project!),
    enabled: !!project && enabled,
  });
}

export function useUpdateBrief() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      project,
      expectedRevision,
      changes,
    }: {
      project: string;
      expectedRevision: number;
      changes: Partial<AdaptationBrief>;
    }) => updateBrief(project, expectedRevision, changes),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "story"] });
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
    },
  });
}

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

export function useImageGenerationMeta(
  project: string | undefined,
  relativeImagePath: string | undefined,
  enabled = true,
  revision?: unknown,
) {
  return useQuery({
    queryKey: ["project", project, "image-generation-meta", relativeImagePath, revision],
    queryFn: () => getImageGenerationMeta(project!, relativeImagePath!),
    enabled: !!project && !!relativeImagePath && enabled,
  });
}

export function useCastAssetVersions(
  project: string, assetType: "character" | "location", assetId: string,
  stateId?: string, refreshKey?: unknown,
) {
  return useQuery({
    queryKey: ["project", project, `${assetType === "character" ? "character-ref" : "location-plate"}-versions`, assetId, stateId ?? null, refreshKey],
    queryFn: () => getCastAssetVersions(project, assetType, assetId, stateId),
    retry: false,
  });
}

export function useRestoreCastAssetVersion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, assetType, assetId, version, stateId }: {
      project: string; assetType: "character" | "location"; assetId: string; version: number; stateId?: string;
    }) => restoreCastAssetVersion(project, assetType, assetId, version, stateId),
    onSuccess: (_data, { project, assetType, assetId, stateId }) => {
      qc.invalidateQueries({ queryKey: ["project", project, `${assetType === "character" ? "character-ref" : "location-plate"}-versions`, assetId, stateId ?? null] });
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
    },
  });
}

export function usePrimaryRefs(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "primary-refs"],
    queryFn: () => getPrimaryRefs(project!),
    enabled: !!project,
  });
}

export function useSetPrimaryRef() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, charId, pose }: { project: string; charId: string; pose: string | null }) =>
      setPrimaryRef(project, charId, pose),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "primary-refs"] });
    },
  });
}

// ── Complete pages and Finish ─────────────────────────────────────────────────

export function useAdaptation(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "adaptation"],
    queryFn: () => getAdaptation(project!),
    enabled: !!project,
  });
}

export function useBookPlan(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "book-plan"],
    queryFn: () => getBookPlan(project!),
    enabled: !!project,
  });
}

export function useStageValidation(
  project: string | undefined,
  stage: "adapt" | "plan",
  enabled = true,
) {
  return useQuery({
    queryKey: ["project", project, "validation", stage],
    queryFn: () => getStageValidation(project!, stage),
    enabled: !!project && enabled,
    retry: false,
  });
}

export function useCompletePages(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "complete-pages"],
    queryFn: () => listCompletePages(project!),
    enabled: !!project,
  });
}

export function useCompletePage(project: string | undefined, pageNumber: number | undefined) {
  return useQuery({
    queryKey: ["project", project, "complete-pages", pageNumber],
    queryFn: () => getCompletePage(project!, pageNumber!),
    enabled: !!project && pageNumber != null,
  });
}

export function useCompletePageBatchEstimate(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "page-batch-estimate"],
    queryFn: () => getCompletePageBatchEstimate(project!),
    enabled: !!project && enabled,
    staleTime: 0,
    retry: false,
  });
}

export function useCompletePageEstimate(
  project: string | undefined,
  pageNumber: number | undefined,
  depiction: "canonical" | "less_graphic" = "canonical",
  enabled = true,
) {
  return useQuery({
    queryKey: ["project", project, "page-estimate", pageNumber, depiction],
    queryFn: () => getCompletePageEstimate(project!, pageNumber!, depiction),
    enabled: !!project && pageNumber != null && enabled,
    staleTime: 0,
    retry: false,
  });
}

export function usePageAnalysisEstimate(
  project: string | undefined,
  pageNumber: number | undefined,
  enabled = true,
) {
  return useQuery({
    queryKey: ["project", project, "page-analysis-estimate", pageNumber],
    queryFn: () => getPageAnalysisEstimate(project!, pageNumber!),
    enabled: !!project && pageNumber != null && enabled,
    staleTime: 0,
    retry: false,
  });
}

function invalidatePageReview(qc: ReturnType<typeof useQueryClient>, project: string, pageNumber?: number) {
  qc.invalidateQueries({ queryKey: ["project", project, "complete-pages"] });
  if (pageNumber != null) {
    qc.invalidateQueries({ queryKey: ["project", project, "complete-pages", pageNumber] });
  }
  qc.invalidateQueries({ queryKey: ["project", project, "status"] });
  qc.invalidateQueries({ queryKey: ["provider-usage", project] });
  qc.invalidateQueries({ queryKey: ["project", project, "generation-jobs"] });
}

export function useGenerateCompletePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      project,
      pageNumber,
      depiction = "canonical",
    }: {
      project: string;
      pageNumber: number;
      depiction?: "canonical" | "less_graphic";
    }) => generateCompletePage(project, pageNumber, depiction),
    onSettled: (_data, _error, { project, pageNumber }) =>
      invalidatePageReview(qc, project, pageNumber),
  });
}

export function useAnalyzeCompletePage() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, pageNumber }: { project: string; pageNumber: number }) =>
      analyzeCompletePage(project, pageNumber),
    onSettled: (_data, _error, { project, pageNumber }) =>
      invalidatePageReview(qc, project, pageNumber),
  });
}


export function useAcceptPageIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, pageNumber, issueId }: { project: string; pageNumber: number; issueId: string }) =>
      acceptPageIssue(project, pageNumber, issueId),
    onSuccess: (_data, { project, pageNumber }) =>
      invalidatePageReview(qc, project, pageNumber),
  });
}

export function useDismissPageIssue() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, pageNumber, issueId }: { project: string; pageNumber: number; issueId: string }) =>
      dismissPageIssue(project, pageNumber, issueId),
    onSuccess: (_data, { project, pageNumber }) =>
      invalidatePageReview(qc, project, pageNumber),
  });
}


export function useFinishPreflight(project: string | undefined, enabled = true) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ["project", project, "finish-preflight"],
    queryFn: async () => {
      try {
        // Finish persists an exact artifact. Reading it first means reopening
        // Book in another tab or browser never rechecks an unchanged edition.
        return await getFinishPreflight(project!);
      } catch (error) {
        if (!isNotFoundError(error)) throw error;
        // A missing artifact means one of Finish's inputs changed (or this is
        // the first Book visit), so run the provider-free preflight once.
        const result = await runFinishPreflight(project!);
        qc.invalidateQueries({ queryKey: ["project", project, "status"] });
        return result.preflight;
      }
    },
    enabled: !!project && enabled,
    retry: false,
  });
}

export function useRunFinishPreflight() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project }: { project: string }) => runFinishPreflight(project),
    onSuccess: (result, { project }) => {
      qc.setQueryData(["project", project, "finish-preflight"], result.preflight);
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
    },
  });
}

export function useExport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, format, force = false }: { project: string; format: "pdf" | "cbz"; force?: boolean }) =>
      triggerExport(project, format, force),
    onSuccess: (result, { project }) => {
      if (result.preflight) {
        qc.setQueryData(["project", project, "finish-preflight"], result.preflight);
      }
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
    },
    onError: (_error, { project }) => {
      // Packaging can invalidate old files before a later format fails.
      qc.invalidateQueries({ queryKey: ["project", project, "finish-preflight"] });
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
    },
  });
}

// ── Styles ───────────────────────────────────────────────────────────────────

export function useStyles(project: string | undefined) {
  return useQuery({
    queryKey: ["project", project, "styles"],
    queryFn: () => getStyles(project!),
    enabled: !!project,
    refetchInterval: (query) => query.state.data?.is_generating ? 1000 : 15_000,
  });
}

export function useSuggestStyles() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, directionId }: { project: string; directionId?: string }) => suggestStyles(project, directionId),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "styles"] });
    },
  });
}

export function useCreateStyleDirection() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, direction, image, withNeighbors }: { project: string; direction: string; image: File | null; withNeighbors: boolean }) =>
      createStyleDirection(project, { direction, image, withNeighbors }),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "styles"] });
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
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

export function useStyleSampleEstimate(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "styles", "sample-estimate"],
    queryFn: () => fetchStyleSampleEstimate(project!),
    enabled: !!project && enabled,
    staleTime: 60_000,
  });
}

export function useStyleDirectionEstimate(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "styles", "direction-estimate"],
    queryFn: () => fetchStyleDirectionEstimate(project!),
    enabled: !!project && enabled,
    staleTime: 60_000,
  });
}

export function useGenerateStyleSamples() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, ids }: { project: string; ids: string[] }) =>
      generateStyleSamples(project, ids),
    onSettled: (_data, _error, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "styles"] });
    },
  });
}

export function useGenerateStyleValidation() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, id }: { project: string; id: string }) =>
      generateStyleValidation(project, id),
    onSettled: (_data, _error, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "styles"] });
    },
  });
}

export function useSetActiveStyle() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, id }: { project: string; id: string }) =>
      setActiveStyle(project, id),
    onSuccess: (_data, { project }) => {
      qc.invalidateQueries({ queryKey: ["project", project, "styles"] });
      qc.invalidateQueries({ queryKey: ["project", project, "status"] });
      qc.invalidateQueries({ queryKey: ["book-lettering-style", project] });
      qc.invalidateQueries({ queryKey: ["lettering-presets", project] });
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
  return useInfiniteQuery({
    // Version the cache key when the response shape changes. The previous
    // flat `transactions` payload is not compatible with InfiniteData pages.
    queryKey: ["credits", "history", "runs-v2"],
    queryFn: ({ pageParam }) => getCreditHistory(pageParam),
    initialPageParam: 0,
    getNextPageParam: (lastPage) => lastPage?.has_more && Array.isArray(lastPage.runs)
      ? lastPage.offset + lastPage.runs.length
      : undefined,
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


export function useProviderUsage(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["provider-usage", project],
    queryFn: () => getProviderUsage(project!),
    enabled: !!project && enabled,
    staleTime: 30_000,
  });
}

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { invalidateProject, splitProjectKey } from "./projectScope";
import {
  addPart,
  deletePart,
  exportParts,
  getPageFlags,
  getPartChapters,
  renamePart,
  replacePartText,
  splitPart,
  type PartTextInput,
} from "./parts";
import {
  addEntity,
  addLook,
  draftEntity,
  editEntity,
  editLook,
  fillVisualAnchor,
  getCastFreshness,
  getDraftEstimate,
  getStoryBibleEditor,
  keepReference,
  mergeEntity,
  reopenCast,
  removeEntity,
  removeLook,
  restoreExcluded,
  type EntityKind,
  type SavedStoryBible,
} from "./storyBible";

// ── Parts ─────────────────────────────────────────────────────────────────────

function refreshParts(qc: QueryClient, project: string) {
  void invalidateProject(qc, project, "status");
  void qc.invalidateQueries({ queryKey: ["projects"] });
}

export function useAddPart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, input }: { project: string; input: PartTextInput }) => addPart(project, input),
    onSuccess: (_data, { project }) => refreshParts(qc, project),
  });
}

export function useReplacePartText() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, part, input }: { project: string; part: string; input: PartTextInput }) =>
      replacePartText(project, part, input),
    onSuccess: (_data, { project }) => refreshParts(qc, project),
  });
}

export function usePartChapters(project: string | undefined, part: string | null | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", project, "part-chapters", part],
    queryFn: () => getPartChapters(project!, part!),
    enabled: !!project && !!part && enabled,
  });
}

export function useSplitPart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, part, boundaries, titles }: {
      project: string; part: string; boundaries: number[]; titles: (string | null)[];
    }) => splitPart(project, part, boundaries, titles),
    onSuccess: (_data, { project }) => {
      refreshParts(qc, project);
      void invalidateProject(qc, project, "part-chapters");
    },
  });
}

export function useRenamePart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, part, title }: { project: string; part: string; title: string }) =>
      renamePart(project, part, title),
    onSuccess: (_data, { project }) => refreshParts(qc, project),
  });
}

export function useDeletePart() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, part }: { project: string; part: string }) => deletePart(project, part),
    onSuccess: (_data, { project }) => refreshParts(qc, project),
  });
}

export function usePageFlags(project: string | undefined) {
  const part = project ? splitProjectKey(project).part : null;
  return useQuery({
    queryKey: ["project", project, "page-flags"],
    queryFn: () => getPageFlags(project!, part!),
    enabled: !!project && !!part,
  });
}

export function useExportParts() {
  return useMutation({
    mutationFn: ({ project, partIds, format }: { project: string; partIds: string[]; format: "pdf" | "cbz" }) =>
      exportParts(project, partIds, format),
  });
}

// ── Story Bible ───────────────────────────────────────────────────────────────

/** Series data is cached once per project, whichever part is open. */
const seriesKey = (project: string | undefined) => (project ? splitProjectKey(project).id : undefined);

export function useStoryBibleEditor(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", seriesKey(project), "story-bible-editor"],
    queryFn: () => getStoryBibleEditor(project!),
    enabled: !!project && enabled,
  });
}

/** An edit changes what every part shows: the Bible, Cast references, stage status and estimates. */
function refreshStoryBible(qc: QueryClient, project: string) {
  for (const resource of ["story-bible-editor", "story-bible", "story", "status", "estimate", "cast-freshness", "page-flags"]) {
    void invalidateProject(qc, project, resource);
  }
}

function useStoryBibleMutation<Variables extends { project: string }>(
  run: (variables: Variables) => Promise<SavedStoryBible>,
) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: run,
    onSuccess: (_saved, { project }) => refreshStoryBible(qc, project),
    // A stale editor reloads so the author sees what changed before retrying.
    onError: (_error, { project }) => void invalidateProject(qc, project, "story-bible-editor"),
  });
}

type EntityTarget = { project: string; kind: EntityKind; id: string; revision: number };

export const useEditEntity = () => useStoryBibleMutation(
  ({ project, kind, id, revision, changes }: EntityTarget & { changes: Record<string, unknown> }) =>
    editEntity(project, kind, id, revision, changes),
);

export const useAddEntity = () => useStoryBibleMutation(
  ({ project, kind, revision, details, sceneIds }: {
    project: string; kind: EntityKind; revision: number; details: Record<string, unknown>; sceneIds: string[];
  }) => addEntity(project, kind, revision, details, sceneIds),
);

export const useRemoveEntity = () => useStoryBibleMutation(
  ({ project, kind, id, revision }: EntityTarget) => removeEntity(project, kind, id, revision),
);

export const useMergeEntity = () => useStoryBibleMutation(
  ({ project, kind, id, into, revision }: EntityTarget & { into: string }) =>
    mergeEntity(project, kind, id, into, revision),
);

export const useAddLook = () => useStoryBibleMutation(
  ({ project, kind, id, revision, details, startsAtScene }: EntityTarget & {
    details: Record<string, unknown>; startsAtScene: string | null;
  }) => addLook(project, kind, id, revision, details, startsAtScene),
);

export const useEditLook = () => useStoryBibleMutation(
  ({ project, kind, id, stateId, revision, changes }: EntityTarget & {
    stateId: string; changes: Record<string, unknown>;
  }) => editLook(project, kind, id, stateId, revision, changes),
);

export const useRemoveLook = () => useStoryBibleMutation(
  ({ project, kind, id, stateId, revision }: EntityTarget & { stateId: string }) =>
    removeLook(project, kind, id, stateId, revision),
);

/** Fills only a blank anchor, so it needs no editor revision; no stage resets. */
export const useFillVisualAnchor = () => useStoryBibleMutation(
  ({ project, ...body }: { project: string; entity_id: string; appearance_state_id: string | null; visual_anchor: string }) =>
    fillVisualAnchor(project, body),
);

export const useRestoreExcluded = () => useStoryBibleMutation(
  ({ project, kind, name, revision }: { project: string; kind: EntityKind; name: string; revision: number }) =>
    restoreExcluded(project, kind, name, revision),
);

export function useDraftEstimate(project: string | undefined, kind: EntityKind, name: string, aliases: string[] = []) {
  const trimmed = name.trim();
  return useQuery({
    queryKey: ["project", seriesKey(project), "draft-estimate", kind, trimmed, aliases],
    queryFn: () => getDraftEstimate(project!, kind, trimmed, aliases),
    enabled: !!project && trimmed.length >= 2,
    staleTime: 60_000,
  });
}

export function useDraftEntity() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, kind, name, aliases, note }: {
      project: string; kind: EntityKind; name: string; aliases?: string[]; note?: string;
    }) => draftEntity(project, kind, { name, aliases, note }),
    onSettled: () => void qc.invalidateQueries({ queryKey: ["credits", "balance"] }),
  });
}

// ── Cast references after edits ───────────────────────────────────────────────

export function useCastFreshness(project: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["project", seriesKey(project), "cast-freshness"],
    queryFn: () => getCastFreshness(project!),
    enabled: !!project && enabled,
  });
}

export function useKeepReference() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project, kind, entityId, stateId }: {
      project: string; kind: EntityKind; entityId: string; stateId: string | null;
    }) => keepReference(project, kind, entityId, stateId),
    onSuccess: (data, { project }) => {
      qc.setQueryData(["project", seriesKey(project), "cast-freshness"], data);
      for (const resource of ["story-bible-editor", "status", "page-flags"]) void invalidateProject(qc, project, resource);
    },
  });
}

export function useReopenCast() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ project }: { project: string }) => reopenCast(project),
    onSuccess: (_data, { project }) => {
      void invalidateProject(qc, project, "status");
      void invalidateProject(qc, project, "estimate");
    },
  });
}

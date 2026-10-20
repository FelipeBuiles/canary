import { useCallback, useEffect, useMemo } from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";
import { useGenerationJobs } from "../api/queries";
import { seedGenerationJob, invalidateGenerationResult } from "../api/generationTracking";
import { generationStatus, isGenerationActive, isGenerationTerminal, type GenerationSubject } from "../lib/generationTracking";
import { maybeShowInsufficientCredits } from "../store/insufficientCredits";
import type { GenerationJob } from "../types/api";

/** Per client, outside the query cache so garbage collection never forgets it. */
const activeByClient = new WeakMap<QueryClient, Map<string, Set<string>>>();
function activeJobs(qc: QueryClient, project: string): Set<string> {
  let projects = activeByClient.get(qc);
  if (!projects) activeByClient.set(qc, projects = new Map());
  let ids = projects.get(project);
  if (!ids) projects.set(project, ids = new Set());
  return ids;
}

type Admission = { job?: GenerationJob; jobs?: GenerationJob[] };
type StartOptions = { actionLabel?: string; onRetry?: () => void };

/** A single poll and policy for every generation subject. UI-specific drafts stay with their owners. */
export function useGenerationTracking(project: string | undefined, enabled = true) {
  const qc = useQueryClient();
  const query = useGenerationJobs(project, [], enabled);
  const admissions = useQuery<GenerationJob[]>({ queryKey: ["project", project, "generation-admissions"], initialData: [], enabled: false });
  useEffect(() => {
    if (!project) return;
    // Only a job this client saw active can newly finish here; history from
    // before this session is already reflected in freshly fetched evidence.
    const active = activeJobs(qc, project);
    for (const job of [...(admissions.data ?? []), ...(query.data?.jobs ?? [])]) {
      if (isGenerationActive(job)) active.add(job.id);
      else if (isGenerationTerminal(job) && active.delete(job.id)) invalidateGenerationResult(qc, project, job);
    }
  }, [project, qc, query.data, admissions.data]);
  const data = useMemo(() => {
    const jobs = [...new Map([...(admissions.data ?? []), ...(query.data?.jobs ?? [])].map(job => [job.id, job])).values()];
    return query.data ? { ...query.data, jobs } : admissions.data?.length
      ? { jobs, current_reference_style_hash: "" } : undefined;
  }, [admissions.data, query.data]);
  const status = useCallback((subject: GenerationSubject, admitted?: GenerationJob | null) => generationStatus({
    ...subject,
    currentStyleHash: subject.currentStyle ? query.data?.current_reference_style_hash : subject.currentStyleHash,
  }, [...(admissions.data ?? []), ...(query.data?.jobs ?? [])], admitted), [query.data, admissions.data]);
  const start = useCallback(async <T,>(subject: GenerationSubject, submit: () => Promise<T>, options?: StartOptions): Promise<T> => {
    try {
      const result = await submit();
      if (project) {
        const admission = result as Admission | undefined;
        for (const job of admission?.jobs ?? (admission?.job ? [admission.job] : [])) seedGenerationJob(qc, project, job);
      }
      return result;
    } catch (error) {
      maybeShowInsufficientCredits(error, { actionLabel: options?.actionLabel ?? subject.kind, onRetry: options?.onRetry });
      throw error;
    }
  }, [project, qc]);
  return { ...query, data, status, start };
}

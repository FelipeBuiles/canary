import { useEffect } from "react";
import { useGenerationJobs } from "../api/queries";
import { useActiveRegens, useRegenStore } from "../store/regen";

/**
 * Polls generation jobs for all active regens in a project and
 * updates the global regen store on completion/failure/progress.
 */
export function useJobPoller(project: string) {
  const activeMap = useActiveRegens(project);
  const updateJob = useRegenStore((s) => s.updateJob);
  const complete = useRegenStore((s) => s.complete);
  const fail = useRegenStore((s) => s.fail);

  const jobIds = Object.values(activeMap)
    .map((r) => r.jobId)
    .filter((id): id is string => !!id);

  const { data } = useGenerationJobs(project, jobIds);

  useEffect(() => {
    if (!data?.jobs.length) return;

    const activeByJobId = new Map(
      Object.values(activeMap)
        .filter((r) => r.jobId)
        .map((r) => [r.jobId, r] as const),
    );

    for (const job of data.jobs) {
      const active = activeByJobId.get(job.id);
      if (!active) continue;

      if (job.status === "complete") {
        complete(project, active.key);
      } else if (job.status === "failed") {
        fail(project, active.key, job.error ?? "Generation failed");
      } else {
        updateJob(project, active.key, job);
      }
    }
  }, [data, activeMap, project, updateJob, complete, fail]);
}

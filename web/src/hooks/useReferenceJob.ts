import { useCallback, useEffect, useRef, useState } from "react";
import { useMutationState, useQueryClient } from "@tanstack/react-query";
import { useGenerationJobs } from "../api/queries";
import type { GenerationJob } from "../types/api";

export function useReferenceJob(project: string, identity: "char_id" | "loc_id" | "prop_id", entityId: string, stateId?: string) {
  const qc = useQueryClient();
  const { data } = useGenerationJobs(project, [], true);
  const scopedId = stateId ? `${entityId}:${stateId}` : entityId;
  const submissions = useMutationState({
    filters: { mutationKey: ["reference-instruction", identity] },
    select: (mutation) => {
      const variables = mutation.state.variables as { project: string; charId?: string; locId?: string; propId?: string; instruction: string } | undefined;
      const id = identity === "char_id" ? variables?.charId : identity === "loc_id" ? variables?.locId : variables?.propId;
      return variables?.project === project && id === scopedId
        ? { ...mutation.state, instruction: variables.instruction }
        : null;
    },
  });
  const submission = submissions.filter((item) => item !== null).at(-1);
  const [submitted, setSubmitted] = useState<GenerationJob | null>(null);
  const [localError, setLocalError] = useState<{ terminalId: string | null; message: string | null } | null>(null);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const [failedImage, setFailedImage] = useState<string | null>(null);
  const observed = useRef<string | null>(null);
  const scope = JSON.stringify([project, identity, entityId, stateId]);
  const [previousScope, setPreviousScope] = useState(scope);
  if (previousScope !== scope) {
    setPreviousScope(scope);
    setSubmitted(null);
    setLocalError(null);
    setFailedImage(null);
  }
  let latest = previousScope === scope ? submitted : null;
  for (const job of data?.jobs ?? []) {
    if (job.payload[identity] !== (stateId ? `${entityId}:${stateId}` : entityId)) continue;
    if (!latest || Date.parse(job.queued_at) >= Date.parse(latest.queued_at)) latest = job;
  }
  const admittedJob = (submission?.data as { job?: GenerationJob } | undefined)?.job;
  if (admittedJob && (!latest || Date.parse(admittedJob.queued_at) > Date.parse(latest.queued_at))) latest = admittedJob;
  const isSubmitting = submission?.status === "pending";
  const submissionIsLatest = !!submission && (!latest || submission.submittedAt >= Date.parse(latest.queued_at));
  const submittedInstruction = submissionIsLatest ? submission.instruction : latest?.payload.instruction;
  const instructionDraft = typeof submittedInstruction === "string" ? submittedInstruction : "";
  const submissionError = submissionIsLatest && submission.status === "error" ? submission.error?.message : null;
  const activeJob = latest?.status === "queued" || latest?.status === "running" ? latest : null;
  const terminalId = latest && !activeJob ? latest.id : null;
  const terminalError = latest?.status === "failed" ? latest.user_message ?? latest.error ?? "Regeneration failed" : null;
  const refreshToken = `${timestamp}-${terminalId ?? ""}`;
  const imageIdentity = JSON.stringify([scope, refreshToken]);
  const imgFailed = failedImage === imageIdentity;
  const regenError = isSubmitting ? null : submissionError ?? (localError?.terminalId === terminalId ? localError.message : terminalError);
  const setImgFailed = useCallback((failed: boolean) => {
    setFailedImage(failed ? imageIdentity : null);
  }, [imageIdentity, setFailedImage]);
  const setRegenError = useCallback((message: string | null) => {
    setLocalError({ terminalId, message });
  }, [terminalId, setLocalError]);

  const admittedJobId = admittedJob?.id;
  useEffect(() => {
    if (admittedJobId) void qc.invalidateQueries({ queryKey: ["project", project, "generation-jobs"] });
  }, [admittedJobId, project, qc]);

  useEffect(() => {
    if (!terminalId || observed.current === terminalId) return;
    observed.current = terminalId;
    void qc.invalidateQueries({ queryKey: ["project", project, "image-generation-meta"] });
    void qc.invalidateQueries({ queryKey: ["project", project, "character-ref-versions"] });
    void qc.invalidateQueries({ queryKey: ["project", project, "status"] });
    void qc.invalidateQueries({ queryKey: ["project", project, "story-bible"] });
  }, [terminalId, project, qc]);

  const setActiveJob = useCallback((job: GenerationJob | null) => {
    setSubmitted(job);
    setLocalError(null);
    void qc.invalidateQueries({ queryKey: ["project", project, "generation-jobs"] });
  }, [project, qc, setSubmitted, setLocalError]);

  return { activeJob, setActiveJob, isSubmitting, instructionDraft, regenError, setRegenError, timestamp: refreshToken, setTimestamp, imgFailed, setImgFailed };
}

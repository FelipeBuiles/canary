import { seedGenerationJob } from "../api/generationTracking";
import { useGenerationTracking } from "./useGenerationTracking";
import { generationStatus, isGenerationActive, isCurrentReferenceJob } from "../lib/generationTracking";
import { useCallback, useState } from "react";
import { useMutationState, useQueryClient } from "@tanstack/react-query";
import type { CastReferenceInput, GenerationJob } from "../types/api";

export function useReferenceJob(project: string, identity: "char_id" | "loc_id" | "prop_id", entityId: string, stateId?: string) {
  const qc = useQueryClient();
  const tracking = useGenerationTracking(project);
  const { data } = tracking;
  const styleHash = data?.current_reference_style_hash;
  const isCurrent = (job: GenerationJob) => isCurrentReferenceJob(job, styleHash);
  const scopedId = stateId ? `${entityId}:${stateId}` : entityId;
  const submissions = useMutationState({
    filters: { mutationKey: ["reference-instruction", identity] },
    select: (mutation) => {
      const variables = mutation.state.variables as { project: string; charId?: string; locId?: string; propId?: string; stateId?: string; referenceAssets?: CastReferenceInput[]; instruction: string } | undefined;
      const id = identity === "char_id" ? variables?.charId : identity === "loc_id" ? variables?.locId : variables?.propId;
      return variables?.project === project && (variables?.stateId ? `${id}:${variables.stateId}` : id) === scopedId
        ? { ...mutation.state, instruction: variables.instruction, referenceAssets: variables.referenceAssets }
        : null;
    },
  });
  const submission = submissions.filter((item) => item !== null).at(-1);
  const [submitted, setSubmitted] = useState<GenerationJob | null>(null);
  const [localError, setLocalError] = useState<{ terminalId: string | null; message: string | null } | null>(null);
  const [timestamp, setTimestamp] = useState(() => Date.now());
  const [failedImage, setFailedImage] = useState<string | null>(null);
  const scope = JSON.stringify([project, identity, entityId, stateId, styleHash]);
  const [previousScope, setPreviousScope] = useState(scope);
  if (previousScope !== scope) {
    setPreviousScope(scope);
    setSubmitted(null);
    setLocalError(null);
    setFailedImage(null);
  }
  const latestPolled = tracking.status({ identity, value: scopedId, currentStyle: true }, previousScope === scope ? submitted : null);
  const admittedJob = (submission?.data as { job?: GenerationJob } | undefined)?.job;
  const latest = generationStatus({ identity, value: scopedId, currentStyleHash: styleHash }, latestPolled ? [latestPolled] : [], admittedJob);
  const isSubmitting = submission?.status === "pending";
  const submissionIsLatest = !!submission && (!admittedJob || isCurrent(admittedJob))
    && (!latest || submission.submittedAt >= Date.parse(latest.queued_at));
  const submittedInstruction = submissionIsLatest ? submission.instruction : latest?.payload.instruction;
  const referenceDraft = (submissionIsLatest ? submission.referenceAssets : latest?.payload.reference_assets) as CastReferenceInput[] | undefined;
  const instructionDraft = typeof submittedInstruction === "string" ? submittedInstruction : "";
  const submissionError = submissionIsLatest && submission.status === "error" ? submission.error?.message : null;
  const activeJob = isGenerationActive(latest) ? latest : null;
  const terminalId = latest && !activeJob ? latest.id : null;
  const terminalError = latest?.status === "failed" ? latest.user_message ?? latest.error ?? "Regeneration failed" : null;
  const refreshToken = `${timestamp}-${styleHash ?? ""}-${terminalId ?? ""}`;
  const imageIdentity = JSON.stringify([scope, refreshToken]);
  const imgFailed = failedImage === imageIdentity;
  const regenError = isSubmitting ? null : submissionError ?? (localError?.terminalId === terminalId ? localError.message : terminalError);
  const setImgFailed = useCallback((failed: boolean) => {
    setFailedImage(failed ? imageIdentity : null);
  }, [imageIdentity, setFailedImage]);
  const setRegenError = useCallback((message: string | null) => {
    setLocalError({ terminalId, message });
  }, [terminalId, setLocalError]);

  const setActiveJob = useCallback((job: GenerationJob | null) => {
    setSubmitted(job);
    setLocalError(null);
    if (job) seedGenerationJob(qc, project, job);
  }, [project, qc, setSubmitted, setLocalError]);

  return { start: tracking.start, activeJob, setActiveJob, isSubmitting, instructionDraft, referenceDraft, regenError, setRegenError, timestamp: refreshToken, setTimestamp, imgFailed, setImgFailed };
}

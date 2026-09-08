import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useGenerationJobs } from "../api/queries";
import type { GenerationJob } from "../types/api";

export function useReferenceJob(project: string, identity: "char_id" | "loc_id" | "prop_id", entityId: string, stateId?: string) {
  const qc = useQueryClient();
  const { data } = useGenerationJobs(project, [], true);
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
  const activeJob = latest?.status === "queued" || latest?.status === "running" ? latest : null;
  const terminalId = latest && !activeJob ? latest.id : null;
  const terminalError = latest?.status === "failed" ? latest.user_message ?? latest.error ?? "Regeneration failed" : null;
  const refreshToken = `${timestamp}-${terminalId ?? ""}`;
  const imageIdentity = JSON.stringify([scope, refreshToken]);
  const imgFailed = failedImage === imageIdentity;
  const regenError = localError?.terminalId === terminalId ? localError.message : terminalError;
  const setImgFailed = useCallback((failed: boolean) => {
    setFailedImage(failed ? imageIdentity : null);
  }, [imageIdentity]);
  const setRegenError = useCallback((message: string | null) => {
    setLocalError({ terminalId, message });
  }, [terminalId]);

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
  }, [project, qc]);

  return { activeJob, setActiveJob, regenError, setRegenError, timestamp: refreshToken, setTimestamp, imgFailed, setImgFailed };
}

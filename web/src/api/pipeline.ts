import type { CastReferenceInput, CastReferenceUpload } from "../types/api";
import { apiFetch, isNotFoundError } from "./client";
import { projectPath, seriesPath } from "./projectScope";
import type {
  CharacterRefVersionsResponse,
  GenerationJob,
  InstructedPlateRegenResponse,
  InstructedPropRegenResponse,
  InstructedRefRegenResponse,
  StageCostEstimate,
  AssetRegenCostEstimate,
} from "../types/api";

export function runPipeline(
  project: string,
  stage?: string,
  rerun?: boolean,
  retryFailed?: boolean,
  queuePages?: boolean,
  confirmedArchivePages?: number,
  thenApprove?: boolean,
): Promise<{ status: string; stage: string }> {
  const params = new URLSearchParams();
  if (stage) params.set("stage", stage);
  if (rerun) params.set("rerun", "1");
  if (retryFailed) params.set("retry_failed", "1");
  if (queuePages) params.set("queue_pages", "1");
  if (confirmedArchivePages !== undefined) params.set("confirmed_archive_pages", String(confirmedArchivePages));
  // Cast only: the server approves Cast and starts Adapt when the run leaves nothing to review.
  if (thenApprove) params.set("then_approve", "1");
  const query = params.toString();
  return apiFetch(`${projectPath(project)}/run${query ? `?${query}` : ""}`, {
    paidAction: true, method: "POST",
  });
}

export function getGenerationJobs(
  project: string,
  ids: string[] = [],
): Promise<{ jobs: GenerationJob[]; current_reference_style_hash: string }> {
  const params = ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&");
  return apiFetch(
    `${projectPath(project)}/jobs${params ? `?${params}` : ""}`,
  );
}

export function cancelQueuedPageJobs(project: string): Promise<{ cancelled_job_ids: string[] }> {
  return apiFetch(`${projectPath(project)}/jobs/cancel-queued-pages`, {
    method: "POST",
  });
}

export function regenRef(
  project: string,
  charId: string,
): Promise<{ status: string; job: GenerationJob; char_id: string }> {
  return apiFetch(
    `${seriesPath(project)}/regen-ref?char_id=${encodeURIComponent(charId)}`,
    { paidAction: true, method: "POST" },
  );
}

export function regenStateRef(
  project: string,
  charId: string,
  stateId: string,
): Promise<{ status: string; job: GenerationJob; char_id: string }> {
  return apiFetch(
    `${seriesPath(project)}/regen-state-ref?char_id=${encodeURIComponent(charId)}&state_id=${encodeURIComponent(stateId)}`,
    { paidAction: true, method: "POST" },
  );
}

export function regenLocationState(
  project: string,
  locId: string,
  stateId: string,
): Promise<{ status: string; job: GenerationJob; loc_id: string }> {
  return apiFetch(
    `${seriesPath(project)}/locations/${encodeURIComponent(locId)}/states/${encodeURIComponent(stateId)}/regenerate`,
    { paidAction: true, method: "POST" },
  );
}

export function getCharacterRefVersions(
  project: string,
  charId: string,
  stateId?: string,
): Promise<CharacterRefVersionsResponse> {
  const params = new URLSearchParams({ char_id: charId });
  if (stateId) params.set("state_id", stateId);
  return apiFetch<CharacterRefVersionsResponse>(
    `${seriesPath(project)}/character-ref-versions?${params.toString()}`,
  ).catch((err) => {
    if (isNotFoundError(err)) {
      return { char_id: charId, state_id: stateId ?? null, has_history: false, versions: [] };
    }
    throw err;
  });
}

export function restoreCharacterRefVersion(
  project: string,
  charId: string,
  version: number,
  stateId?: string,
): Promise<CharacterRefVersionsResponse> {
  const params = new URLSearchParams({ char_id: charId, version: String(version) });
  if (stateId) params.set("state_id", stateId);
  return apiFetch(
    `${seriesPath(project)}/character-ref-versions/restore?${params.toString()}`,
    { method: "POST" },
  );
}

export function getCastAssetVersions(
  project: string, assetType: "character" | "location", assetId: string, stateId?: string,
): Promise<Pick<CharacterRefVersionsResponse, "versions">> {
  if (assetType === "character") return getCharacterRefVersions(project, assetId, stateId);
  const params = new URLSearchParams({ loc_id: assetId });
  if (stateId) params.set("state_id", stateId);
  return apiFetch(`${seriesPath(project)}/location-plate-versions?${params}`);
}

export function restoreCastAssetVersion(
  project: string, assetType: "character" | "location", assetId: string, version: number, stateId?: string,
): Promise<Pick<CharacterRefVersionsResponse, "versions">> {
  if (assetType === "character") return restoreCharacterRefVersion(project, assetId, version, stateId);
  const params = new URLSearchParams({ loc_id: assetId, version: String(version) });
  if (stateId) params.set("state_id", stateId);
  return apiFetch(`${seriesPath(project)}/location-plate-versions/restore?${params}`, { method: "POST" });
}

export function regenPlate(
  project: string,
  locId: string,
): Promise<{ status: string; job: GenerationJob; loc_id: string }> {
  return apiFetch(
    `${seriesPath(project)}/regen-plate?loc_id=${encodeURIComponent(locId)}`,
    { paidAction: true, method: "POST" },
  );
}

/** Store an author image for a Cast correction. No spend. */
export function uploadCastReference(project: string, image: File): Promise<CastReferenceUpload> {
  const form = new FormData();
  form.append("image", image);
  return apiFetch(`${seriesPath(project)}/cast/reference-uploads`, { method: "POST", headers: {}, body: form });
}

export function regenRefWithInstruction(
  project: string,
  charId: string,
  instruction: string,
  referenceAssets?: CastReferenceInput[],
  stateId?: string,
): Promise<InstructedRefRegenResponse> {
  return apiFetch(
    stateId ? `${seriesPath(project)}/characters/${encodeURIComponent(charId)}/states/${encodeURIComponent(stateId)}/regenerate-instructed` : `${seriesPath(project)}/regen-ref-instructed`,
    {
      paidAction: true, method: "POST",
      body: JSON.stringify({ ...(stateId ? {} : { char_id: charId }), instruction, reference_assets: referenceAssets }),
    },
  );
}

export function regenPlateWithInstruction(
  project: string,
  locId: string,
  instruction: string,
  referenceAssets?: CastReferenceInput[],
  stateId?: string,
): Promise<InstructedPlateRegenResponse> {
  return apiFetch(
    stateId ? `${seriesPath(project)}/locations/${encodeURIComponent(locId)}/states/${encodeURIComponent(stateId)}/regenerate-instructed` : `${seriesPath(project)}/regen-plate-instructed`,
    {
      paidAction: true, method: "POST",
      body: JSON.stringify({ ...(stateId ? {} : { loc_id: locId }), instruction, reference_assets: referenceAssets }),
    },
  );
}

export function regenProp(
  project: string,
  propId: string,
): Promise<{ status: string; job: GenerationJob; prop_id: string }> {
  return apiFetch(
    `${seriesPath(project)}/regen-prop?prop_id=${encodeURIComponent(propId)}`,
    { paidAction: true, method: "POST" },
  );
}

export function regenPropWithInstruction(
  project: string,
  propId: string,
  instruction: string,
  referenceAssets?: CastReferenceInput[],
  stateId?: string,
): Promise<InstructedPropRegenResponse> {
  return apiFetch(
    stateId ? `${seriesPath(project)}/props/${encodeURIComponent(propId)}/states/${encodeURIComponent(stateId)}/regenerate-instructed` : `${seriesPath(project)}/regen-prop-instructed`,
    {
      paidAction: true, method: "POST",
      body: JSON.stringify({ ...(stateId ? {} : { prop_id: propId }), instruction, reference_assets: referenceAssets }),
    },
  );
}

export function resetStale(project: string): Promise<{ status: string; reset: string[]; message: string }> {
  return apiFetch(`${projectPath(project)}/reset-stale`, {
    method: "POST",
  });
}

export function approveStage(
  project: string,
  stage: string,
): Promise<{ status: string; stage: string }> {
  return apiFetch(
    `${projectPath(project)}/approve/${encodeURIComponent(stage)}`,
    { paidAction: stage === "brief" || stage === "cast", method: "POST" },
  );
}

export function regenExtract(
  project: string,
): Promise<{ status: string; stage: string }> {
  return apiFetch(
    `${projectPath(project)}/regen-extract`,
    { paidAction: true, method: "POST" },
  );
}

export function fetchStageEstimate(
  project: string,
  stage: string,
  rerun = false,
): Promise<StageCostEstimate> {
  return apiFetch(
    `${projectPath(project)}/estimate?stage=${encodeURIComponent(stage)}${rerun ? "&rerun=true" : ""}`,
  );
}

export function fetchAssetRegenEstimate(
  project: string,
  assetType: "character" | "location" | "prop",
  assetId: string,
  stateId?: string,
  referenceCount?: number,
): Promise<AssetRegenCostEstimate> {
  const params = new URLSearchParams({
    asset_type: assetType,
    asset_id: assetId,
  });
  if (stateId) params.set("state_id", stateId);
  if (referenceCount !== undefined) params.set("reference_count", String(referenceCount));
  return apiFetch(
    `${seriesPath(project)}/asset-regen-estimate?${params.toString()}`,
  );
}

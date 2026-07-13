import { apiFetch } from "./client";
import type {
  CharacterRefVersionsResponse,
  GenerationJob,
  InstructedPanelRegenResponse,
  InstructedPlateRegenResponse,
  InstructedPropRegenResponse,
  InstructedRefRegenResponse,
  StageCostEstimate,
  RegenCostEstimate,
  AssetRegenCostEstimate,
  GenerationRequestPreview,
} from "../types/api";

function generationRequestPath(project: string, suffix: string) {
  return `/projects/${encodeURIComponent(project)}/generation-requests${suffix}`;
}

export function previewGenerationRequest(
  project: string,
  sceneId: string,
  panelNumber: number,
  imageModelAlias?: string | null,
  devContent = false,
  preparedRequestId?: string | null,
): Promise<GenerationRequestPreview> {
  const params = new URLSearchParams({
    scene_id: sceneId,
    panel_number: String(panelNumber),
  });
  if (imageModelAlias) params.set("image_model_alias", imageModelAlias);
  if (preparedRequestId) params.set("prepared_request_id", preparedRequestId);
  if (devContent) params.set("dev_content", "1");
  return apiFetch<GenerationRequestPreview>(
    `${generationRequestPath(project, "/preview")}?${params.toString()}`,
  );
}

export function prepareGenerationRequest(
  project: string,
  sceneId: string,
  panelNumber: number,
  imageModelAlias?: string | null,
): Promise<GenerationRequestPreview> {
  return apiFetch<GenerationRequestPreview>(generationRequestPath(project, "/prepare"), {
    method: "POST",
    body: JSON.stringify({
      scene_id: sceneId,
      panel_number: panelNumber,
      ...(imageModelAlias ? { image_model_alias: imageModelAlias } : {}),
    }),
  });
}

export function getGenerationRequest(
  project: string,
  requestId: string,
  devContent = false,
): Promise<GenerationRequestPreview> {
  const query = devContent ? "?dev_content=1" : "";
  return apiFetch<GenerationRequestPreview>(
    `${generationRequestPath(project, `/${encodeURIComponent(requestId)}`)}${query}`,
  );
}

export function runPipeline(
  project: string,
  stage?: string,
  rerun?: boolean,
  retryFailed?: boolean,
): Promise<{ status: string; stage: string }> {
  const params = new URLSearchParams();
  if (stage) params.set("stage", stage);
  if (rerun) params.set("rerun", "1");
  if (retryFailed) params.set("retry_failed", "1");
  const query = params.toString();
  return apiFetch(`/projects/${encodeURIComponent(project)}/run${query ? `?${query}` : ""}`, {
    method: "POST",
  });
}

export function regenPanel(
  project: string,
  sceneId: string,
  panelNumber: number,
  imageModelAlias?: string | null,
  preparedRequestId?: string | null,
): Promise<{ status: string; job: GenerationJob; scene_id: string; panel_number: number; planned_panel_id?: string | null; request_id?: string | null }> {
  const params = new URLSearchParams({
    scene_id: sceneId,
    panel_number: String(panelNumber),
  });
  if (imageModelAlias) params.set("image_model_alias", imageModelAlias);
  if (preparedRequestId) params.set("prepared_request_id", preparedRequestId);
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen?${params.toString()}`,
    { method: "POST" },
  );
}

export function regenPanelWithInstruction(
  project: string,
  sceneId: string,
  panelNumber: number,
  instruction: string,
  imageModelAlias?: string | null,
): Promise<InstructedPanelRegenResponse> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-instructed`,
    {
      method: "POST",
      body: JSON.stringify({
        scene_id: sceneId,
        panel_number: panelNumber,
        instruction,
        ...(imageModelAlias ? { image_model_alias: imageModelAlias } : {}),
      }),
    },
  );
}

export function getGenerationJobs(
  project: string,
  ids: string[],
): Promise<{ jobs: GenerationJob[] }> {
  const params = ids.map((id) => `ids=${encodeURIComponent(id)}`).join("&");
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/generation-jobs${params ? `?${params}` : ""}`,
  );
}

export function regenRef(
  project: string,
  charId: string,
): Promise<{ status: string; job: GenerationJob; char_id: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-ref?char_id=${encodeURIComponent(charId)}`,
    { method: "POST" },
  );
}

export function regenStateRef(
  project: string,
  charId: string,
  stateId: string,
): Promise<{ status: string; job: GenerationJob; char_id: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-state-ref?char_id=${encodeURIComponent(charId)}&state_id=${encodeURIComponent(stateId)}`,
    { method: "POST" },
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
    `/projects/${encodeURIComponent(project)}/character-ref-versions?${params.toString()}`,
  ).catch((err) => {
    if (err instanceof Error && err.message.startsWith("API 404:")) {
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
    `/projects/${encodeURIComponent(project)}/character-ref-versions/restore?${params.toString()}`,
    { method: "POST" },
  );
}

export function regenPlate(
  project: string,
  locId: string,
): Promise<{ status: string; job: GenerationJob; loc_id: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-plate?loc_id=${encodeURIComponent(locId)}`,
    { method: "POST" },
  );
}

export function regenRefWithInstruction(
  project: string,
  charId: string,
  instruction: string,
): Promise<InstructedRefRegenResponse> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-ref-instructed`,
    {
      method: "POST",
      body: JSON.stringify({ char_id: charId, instruction }),
    },
  );
}

export function regenPlateWithInstruction(
  project: string,
  locId: string,
  instruction: string,
): Promise<InstructedPlateRegenResponse> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-plate-instructed`,
    {
      method: "POST",
      body: JSON.stringify({ loc_id: locId, instruction }),
    },
  );
}

export function regenProp(
  project: string,
  propId: string,
): Promise<{ status: string; job: GenerationJob; prop_id: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-prop?prop_id=${encodeURIComponent(propId)}`,
    { method: "POST" },
  );
}

export function regenPropWithInstruction(
  project: string,
  propId: string,
  instruction: string,
): Promise<InstructedPropRegenResponse> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-prop-instructed`,
    {
      method: "POST",
      body: JSON.stringify({ prop_id: propId, instruction }),
    },
  );
}

export function resetStale(project: string): Promise<{ status: string; reset: string[]; message: string }> {
  return apiFetch(`/projects/${encodeURIComponent(project)}/reset-stale`, {
    method: "POST",
  });
}

export function approveStage(
  project: string,
  stage: string,
): Promise<{ status: string; stage: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/approve/${encodeURIComponent(stage)}`,
    { method: "POST" },
  );
}

export function regenExtract(
  project: string,
): Promise<{ status: string; stage: string }> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-extract`,
    { method: "POST" },
  );
}

export function fetchStageEstimate(
  project: string,
  stage: string,
): Promise<StageCostEstimate> {
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/estimate?stage=${encodeURIComponent(stage)}`,
  );
}

export function fetchRegenEstimate(
  project: string,
  sceneId: string,
  panelNumber: number,
  imageModelAlias?: string | null,
): Promise<RegenCostEstimate> {
  const params = new URLSearchParams({
    scene_id: sceneId,
    panel_number: String(panelNumber),
  });
  if (imageModelAlias) params.set("image_model_alias", imageModelAlias);
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/regen-estimate?${params.toString()}`,
  );
}

export function fetchAssetRegenEstimate(
  project: string,
  assetType: "character" | "location" | "prop",
  assetId: string,
  stateId?: string,
): Promise<AssetRegenCostEstimate> {
  const params = new URLSearchParams({
    asset_type: assetType,
    asset_id: assetId,
  });
  if (stateId) params.set("state_id", stateId);
  return apiFetch(
    `/projects/${encodeURIComponent(project)}/asset-regen-estimate?${params.toString()}`,
  );
}

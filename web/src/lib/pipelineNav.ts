import { STAGE_ORDER } from "../types/api";
import type { ProjectStatus, StageName } from "../types/api";

export function findPendingStage(status: ProjectStatus | undefined): StageName | undefined {
  return STAGE_ORDER.find((stage) => {
    const stageStatus = status?.stages[stage]?.status;
    return !stageStatus || stageStatus === "pending";
  });
}

export function findPendingStageAfter(
  status: ProjectStatus | undefined,
  approvedStage: StageName,
): StageName | undefined {
  const approvedIndex = STAGE_ORDER.indexOf(approvedStage);
  if (approvedIndex < 0) return undefined;
  return STAGE_ORDER.slice(approvedIndex + 1).find((stage) => {
    const stageStatus = status?.stages[stage]?.status;
    return !stageStatus || stageStatus === "pending";
  });
}

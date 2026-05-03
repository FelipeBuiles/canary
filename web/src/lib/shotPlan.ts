import type { ProjectStatus, StageInfo, StageStatus } from "../types/api";

export type ShotPlanBackendStage = "plan" | "storyboard";

export type ShotPlanSubStatus = {
  layoutLabel: string;
  boardLabel: string;
  detail: string;
  status: StageStatus;
  failedCount: number;
  itemsDone: number;
  itemsTotal: number;
};

export type ShotPlanAction =
  | {
      kind: "run" | "rerun";
      backendStage: ShotPlanBackendStage;
      estimateStage: ShotPlanBackendStage;
      label: string;
    }
  | {
      kind: "approve";
      backendStage: ShotPlanBackendStage;
      estimateStage?: ShotPlanBackendStage;
      label: string;
      runAfterApprove?: boolean;
    }
  | { kind: "none"; label: string };

function info(status: ProjectStatus | undefined, stage: ShotPlanBackendStage): StageInfo | undefined {
  return status?.stages[stage];
}

function label(stageInfo: StageInfo | undefined, completeText: string, pendingText: string) {
  if (!stageInfo || stageInfo.status === "pending") return pendingText;
  if (stageInfo.status === "awaiting_review") return "needs review";
  if (stageInfo.status === "running") return "running";
  if (stageInfo.status === "failed" || stageInfo.items_failed.length > 0) return "failed";
  if (stageInfo.status === "complete") return completeText;
  return pendingText;
}

export function getShotPlanSubStatus(status: ProjectStatus | undefined): ShotPlanSubStatus {
  const plan = info(status, "plan");
  const storyboard = info(status, "storyboard");
  const failedCount = (plan?.items_failed.length ?? 0) + (storyboard?.items_failed.length ?? 0);
  const itemsDone = (plan?.items_done ?? 0) + (storyboard?.items_done ?? 0);
  const itemsTotal = (plan?.items_total ?? 0) + (storyboard?.items_total ?? 0);

  let compositeStatus: StageStatus = "pending";
  if (plan?.status === "failed" || storyboard?.status === "failed") {
    compositeStatus = "failed";
  } else if (plan?.status === "running" || storyboard?.status === "running") {
    compositeStatus = "running";
  } else if (failedCount > 0) {
    compositeStatus = "failed";
  } else if (plan?.status === "awaiting_review" || storyboard?.status === "awaiting_review") {
    compositeStatus = "awaiting_review";
  } else if (plan?.status === "complete" && storyboard?.status === "complete") {
    compositeStatus = "complete";
  }

  const layoutLabel = label(plan, "complete", "pending");
  const boardLabel = plan?.status === "complete"
    ? label(storyboard, "complete", "pending")
    : "locked";

  return {
    layoutLabel,
    boardLabel,
    detail: `Layout ${layoutLabel} · Board ${boardLabel}`,
    status: compositeStatus,
    failedCount,
    itemsDone,
    itemsTotal,
  };
}

export function getShotPlanAction(status: ProjectStatus | undefined): ShotPlanAction {
  const plan = info(status, "plan");
  const storyboard = info(status, "storyboard");

  if (plan?.status === "failed" || (plan?.items_failed.length ?? 0) > 0) {
    return { kind: "rerun", backendStage: "plan", estimateStage: "plan", label: "Fix Shot Plan" };
  }
  if (!plan || plan.status === "pending") {
    return { kind: "run", backendStage: "plan", estimateStage: "plan", label: "Run Shot Plan" };
  }
  if (plan.status === "running") return { kind: "none", label: "Shot Plan Running" };
  if (plan.status === "awaiting_review") {
    return {
      kind: "approve",
      backendStage: "plan",
      estimateStage: "storyboard",
      label: "Approve Layout & Build Board",
      runAfterApprove: true,
    };
  }

  if (storyboard?.status === "failed" || (storyboard?.items_failed.length ?? 0) > 0) {
    return { kind: "rerun", backendStage: "storyboard", estimateStage: "storyboard", label: "Fix Board" };
  }
  if (!storyboard || storyboard.status === "pending") {
    return { kind: "run", backendStage: "storyboard", estimateStage: "storyboard", label: "Build Board" };
  }
  if (storyboard.status === "running") return { kind: "none", label: "Board Running" };
  if (storyboard.status === "awaiting_review") {
    return { kind: "approve", backendStage: "storyboard", label: "Approve Shot Plan & Continue" };
  }

  return { kind: "none", label: "Shot Plan Complete" };
}

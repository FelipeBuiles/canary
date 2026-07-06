import { useCreditBalance, useProjectStatus, useStageEstimate } from "../api/queries";
import type { StageName } from "../types/api";

export type NeedsCredits =
  | { blocked: false }
  | {
      blocked: true;
      balance: number;
      required: number;
      shortfall: number;
      reason: "persisted" | "heuristic";
    };

/**
 * Decide whether a stage is blocked on credits, for the in-room CreditsGate
 * panel. Two signals, in priority order:
 *
 * 1. Persisted (authoritative): the stage is `failed` with
 *    `error_code === "insufficient_credits"` — survives a page reload. Uses
 *    the persisted `required_credits`; the Balance column always shows the
 *    LIVE balance (polled, so it's at least as fresh as the persisted
 *    snapshot and updates after a purchase).
 * 2. Heuristic: the stage is `pending` or non-credit `failed`, and the live
 *    balance is below the stage's live estimate (from the /estimate endpoint,
 *    which calls the stage's estimate_cost hook — NOT the
 *    `estimated_cost_credits` field on StageInfo, which is 0 until a stage
 *    has actually run). This catches the brand-new 0-credit user before they
 *    ever hit Run.
 *
 * Returns `{ blocked: false }` while data is still loading so the room can
 * render its normal loading state.
 */
export function useNeedsCredits(
  project: string | undefined,
  stage: StageName,
): NeedsCredits {
  const { data: status } = useProjectStatus(project);
  const { data: balanceData } = useCreditBalance();
  const stageInfo = status?.stages?.[stage];
  const liveBalance = balanceData?.balance_credits ?? 0;

  // Only fetch the estimate for stages that could heuristically block
  // (pending or non-credit failed) — but the hook itself MUST be called
  // unconditionally (Rules of Hooks). The `enabled` flag gates the fetch.
  const isRunnableState =
    stageInfo?.status === "pending" ||
    (stageInfo?.status === "failed" && stageInfo.error_code !== "insufficient_credits");
  const { data: estimateData } = useStageEstimate(project, stage, isRunnableState);

  // All hooks above this point. Early returns are safe below.
  if (!stageInfo) return { blocked: false };

  // 1. Persisted credit failure.
  if (
    stageInfo.status === "failed" &&
    stageInfo.error_code === "insufficient_credits"
  ) {
    const required = stageInfo.required_credits ?? 0;
    return {
      blocked: true,
      balance: liveBalance,
      required,
      shortfall: Math.max(0, required - liveBalance),
      reason: "persisted",
    };
  }

  // 2. Heuristic: not yet run (or non-credit failed), but can't afford it.
  if (isRunnableState) {
    const estimate = estimateData?.estimate_credits ?? 0;
    if (estimate > 0 && liveBalance < estimate) {
      return {
        blocked: true,
        balance: liveBalance,
        required: estimate,
        shortfall: estimate - liveBalance,
        reason: "heuristic",
      };
    }
  }

  return { blocked: false };
}

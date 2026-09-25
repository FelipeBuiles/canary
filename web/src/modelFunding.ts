export type ModelFunding = "api" | "codex_subscription" | "claude_subscription";

/** Model picker groups, in display order, with their (translatable) labels. */
export const MODEL_FUNDING_GROUPS: ReadonlyArray<{ funding: ModelFunding; label: string }> = [
  { funding: "api", label: "API billing" },
  { funding: "codex_subscription", label: "Codex subscription" },
  { funding: "claude_subscription", label: "Claude subscription" },
];

export function fundingLabel(funding: ModelFunding | undefined): string {
  return MODEL_FUNDING_GROUPS.find((group) => group.funding === (funding ?? "api"))?.label ?? "API billing";
}

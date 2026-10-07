/** Also recognize saved failures from before structured stage errors were retained. */
export function isStorageLimitError(error?: string | null, code?: string | null): boolean {
  return code === "storage_budget_exceeded"
    || !!error?.includes("storage_budget_exceeded")
    || !!error?.startsWith("Account storage is full.");
}

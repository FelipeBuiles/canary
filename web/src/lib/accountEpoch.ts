let epoch = 0;
export let accountIdentity: string | null = null;
const pending = new Set<AbortController>();

export function accountEpoch() { return epoch; }
export function clearAccountRequests(account: string | null = null) {
  accountIdentity = account;
  epoch += 1;
  for (const controller of pending) controller.abort();
  pending.clear();
}
export function trackAccountRequest(controller: AbortController) {
  pending.add(controller);
  return () => pending.delete(controller);
}
export function assertAccountEpoch(expected: number) {
  if (expected !== epoch) throw new DOMException("Account changed", "AbortError");
}

import { claimGa4Signup } from "../api/events";
import { ga4Ready, trackGa4Signup } from "./ga4";

let currentAccount: string | undefined;
const attempted = new Set<string>();

export function setGa4SignupAccount(userId: string | undefined): void {
  currentAccount = userId;
}

/** Survives React remounts: an effect cleanup must not consume a signup claim. */
export async function reportGa4Signup(userId: string): Promise<void> {
  if (currentAccount !== userId || !ga4Ready() || attempted.has(userId)) return;
  attempted.add(userId);
  const claimed = await claimGa4Signup();
  if (claimed && currentAccount === userId && ga4Ready()) trackGa4Signup();
}

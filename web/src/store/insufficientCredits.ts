import { create } from "zustand";
import type { InsufficientCreditsInfo } from "../api/client";
import { isInsufficientCreditsError } from "../api/client";

interface OpenOptions {
  info: InsufficientCreditsInfo;
  actionLabel?: string;
  onRetry?: () => void;
}

interface State {
  open: boolean;
  info: InsufficientCreditsInfo | null;
  actionLabel: string | null;
  onRetry: (() => void) | null;
  show: (options: OpenOptions) => void;
  close: () => void;
}

export const useInsufficientCreditsStore = create<State>((set) => ({
  open: false,
  info: null,
  actionLabel: null,
  onRetry: null,
  show: ({ info, actionLabel, onRetry }) =>
    set({
      open: true,
      info,
      actionLabel: actionLabel ?? null,
      onRetry: onRetry ?? null,
    }),
  close: () => set({ open: false, info: null, actionLabel: null, onRetry: null }),
}));

/**
 * If `err` is an InsufficientCreditsError, surface the buy-credits dialog and
 * return true. Caller can then skip its own error reporting.
 */
export function maybeShowInsufficientCredits(
  err: unknown,
  options?: { actionLabel?: string; onRetry?: () => void },
): boolean {
  if (!isInsufficientCreditsError(err)) return false;
  useInsufficientCreditsStore.getState().show({
    info: err.insufficientCredits,
    actionLabel: options?.actionLabel,
    onRetry: options?.onRetry,
  });
  return true;
}

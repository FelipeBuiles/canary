import { QueryClient, hashKey } from "@tanstack/react-query";
import { ApiError } from "./client";

/**
 * Client errors are deterministic: the same request fails the same way, so
 * retrying only multiplies log noise and latency. This mattered in practice —
 * every artifact route (`/pages`, `/book-plan`, `/adaptation`) answers 404
 * until its stage has run, so react-query's default `retry: 3` turned each
 * normal pre-stage read into four requests spread over ~7s of backoff.
 */
export function retryPolicy(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) {
    return false;
  }
  return failureCount < 3;
}

export function createAccountQueryClient(account: string | null) {
  return new QueryClient({
    defaultOptions: {
      queries: {
        retry: retryPolicy,
        queryKeyHashFn: (key) => hashKey(["account", account, ...key]),
      },
      mutations: { retry: false },
    },
  });
}

export let queryClient = createAccountQueryClient(null);

export function replaceAccountQueryClient(account: string | null) {
  void queryClient.cancelQueries();
  queryClient.clear();
  queryClient = createAccountQueryClient(account);
}

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

/**
 * Account-independent reads, shared by signed-out and signed-in visitors. They
 * are hashed without an account so restoring a session keeps their data.
 */
const PUBLIC_QUERY_ROOTS = new Set(["short-stories", "public-book"]);
const isPublicQuery = (key: readonly unknown[]) => typeof key[0] === "string" && PUBLIC_QUERY_ROOTS.has(key[0]);

interface AccountScope { account: string | null; adopted: boolean }
const scopes = new WeakMap<QueryClient, AccountScope>();

export function createAccountQueryClient(account: string | null, adopted = true) {
  const scope: AccountScope = { account, adopted };
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: retryPolicy,
        queryKeyHashFn: (key) => hashKey(isPublicQuery(key) ? ["public", ...key] : ["account", scope.account, ...key]),
      },
      mutations: { retry: false },
    },
  });
  scopes.set(client, scope);
  return client;
}

/** The startup client has not yet been bound to an account. */
export let queryClient = createAccountQueryClient(null, false);
/** Changes only when a client is replaced; keys the provider subtree. */
export let queryClientEpoch = 0;

export function replaceAccountQueryClient(account: string | null) {
  const scope = scopes.get(queryClient);
  if (scope && !scope.adopted) {
    // Before any account was known only public reads could run (private
    // routes wait for auth). Bind this client in place: no remount, and the
    // public page already on screen keeps its data.
    scope.adopted = true;
    queryClient.removeQueries({ predicate: (query) => !isPublicQuery(query.queryKey) });
    scope.account = account;
    return;
  }
  void queryClient.cancelQueries();
  queryClient.clear();
  queryClient = createAccountQueryClient(account);
  queryClientEpoch += 1;
}

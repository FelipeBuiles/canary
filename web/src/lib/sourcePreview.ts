import { ApiError } from "../api/client";

/** A deterministic rejection (unreadable, unsupported, too large) fails creation the same way. */
export function previewRejected(error: unknown) {
  return error instanceof ApiError && error.status >= 400 && error.status < 500 && ![401, 403, 408, 429].includes(error.status);
}

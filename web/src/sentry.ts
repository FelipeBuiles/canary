/**
 * Frontend Sentry bootstrap.
 *
 * Activated by `VITE_SENTRY_DSN` (exposed to the client by Vite). No DSN → the
 * import is a no-op and adds ~zero cost. Backend errors are tracked separately
 * (server/sentry.py); this captures client-side errors and the route that failed.
 */
import * as Sentry from "@sentry/react";

export function initSentry(): void {
	const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
	if (!dsn) return;

	Sentry.init({
		dsn,
		environment: import.meta.env.VITE_CANARY_ENV ?? "dev",
		release: import.meta.env.VITE_CANARY_VERSION,
		// Error capture only; traces stay on the backend (Langfuse/OTel) to avoid
		// double-counting and to keep the client bundle quiet.
		tracesSampleRate: 0,
		// Session replay off for launch — opt in later once we want it.
		replaysSessionSampleRate: 0,
		replaysOnErrorSampleRate: 0,
		// Never exfiltrate auth tokens. PII off globally.
		sendDefaultPii: false,
	});
}

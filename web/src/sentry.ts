/**
 * Frontend Sentry bootstrap.
 *
 * Activated by `VITE_SENTRY_DSN` (exposed to the client by Vite). No DSN → the
 * import is a no-op. Backend errors are tracked separately (server/sentry.py);
 * this captures client errors plus optional sampled traces/error replay.
 */
import * as Sentry from "@sentry/react";

export function setSentryUser(userId: string | null): void {
	Sentry.setUser(userId ? { id: userId } : null);
}

export function initSentry(): void {
	const dsn = import.meta.env.VITE_SENTRY_DSN as string | undefined;
	if (!dsn) return;
	const configuredTraceRate = Number(import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE ?? 0);
	const configuredReplayRate = Number(import.meta.env.VITE_SENTRY_REPLAYS_ON_ERROR_SAMPLE_RATE ?? 0);
	const tracesSampleRate = Number.isFinite(configuredTraceRate)
		? Math.min(1, Math.max(0, configuredTraceRate))
		: 0;
	const replaysOnErrorSampleRate = Number.isFinite(configuredReplayRate)
		? Math.min(1, Math.max(0, configuredReplayRate))
		: 0;

	Sentry.init({
		dsn,
		environment: import.meta.env.VITE_CANARY_ENV ?? "dev",
		release: import.meta.env.VITE_CANARY_VERSION,
		// Sampling defaults to zero and is enabled explicitly at build time.
		tracesSampleRate,
		// Session replay off for launch — opt in later once we want it.
		replaysSessionSampleRate: 0,
		replaysOnErrorSampleRate,
		integrations: replaysOnErrorSampleRate > 0
			? [Sentry.replayIntegration({ maskAllText: true, blockAllMedia: true })]
			: [],
		// Never exfiltrate auth tokens. PII off globally.
		sendDefaultPii: false,
		beforeSend(event) {
			if (event.request?.headers) {
				for (const key of Object.keys(event.request.headers)) {
					if (["authorization", "cookie", "x-api-key", "x-canary-ops-token"].includes(key.toLowerCase())) {
						event.request.headers[key] = "[Filtered]";
					}
				}
			}
			return event;
		},
	});
}

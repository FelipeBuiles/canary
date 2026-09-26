# PostHog integration recipes checked for Canary

Implementation follow-up: the user authorized consolidation without a separate
synthetic-journey gate. See the [current operating guide](../reference/observability.md)
for implemented behavior and remaining activation steps. This research records the
decision basis, not evidence that cloud delivery is live.

**Status: Historical research.** Checked September 26, 2026 during the authorized
implementation. This records vendor recipes and implementation choices, not
proof of successful delivery to a configured PostHog account. The user waived
the separate synthetic-journey gate and authorized consolidation now.

## Official skills reviewed

Read PostHog's [skills collection](https://github.com/PostHog/skills), including
the SKILL.md and relevant bundled references for
[FastAPI](https://github.com/PostHog/skills/tree/main/skills/posthog/all/skills/integration-fastapi),
[React/Vite](https://github.com/PostHog/skills/tree/main/skills/posthog/all/skills/integration-react-vite),
[Python errors](https://github.com/PostHog/skills/tree/main/skills/posthog/all/skills/error-tracking-python),
[React errors](https://github.com/PostHog/skills/tree/main/skills/posthog/all/skills/error-tracking-react),
[Python logs](https://github.com/PostHog/skills/tree/main/skills/posthog/all/skills/logs-python),
and [AI analytics](https://github.com/PostHog/skills/tree/main/skills/posthog/all/skills/llm-analytics-setup).
Also reviewed the maintained AI plugin's
[error instrumentation skill](https://github.com/PostHog/ai-plugin/blob/main/skills/instrument-error-tracking/SKILL.md).

The recipes are useful examples, not a substitute for Canary's contracts.
The FastAPI skill inconsistently recommends module configuration and instance
configuration; use one owned client in application startup/shutdown. Its example
uses email identity and raw exception responses; Canary should use opaque
authenticated user IDs and preserve safe HTTP errors. The generic instruction
to add alongside existing integrations is superseded by the user's explicit
replacement request. Missing deployment credentials must not block local work.

## Python events and exceptions

Use `Posthog(project_api_key=token, host=host, ...)` and explicit keyword calls:
`client.capture(event, distinct_id=user_id, properties=properties)` and
`client.capture_exception(exc, distinct_id=user_id, properties=properties,
disable_geoip=True)`. Capture FastAPI and worker failures explicitly: Python
autocapture hooks do not see all exceptions handled by frameworks. Shut the
client down during application shutdown; avoid blocking request handling on
network delivery. Bound the event queue and exporter timeout.
[Python recipe](https://github.com/PostHog/skills/blob/main/skills/posthog/all/skills/error-tracking-python/references/python.md),
[client source](https://github.com/PostHog/posthog-python/blob/main/posthog/client.py)

`before_send` receives the complete event, including
`properties.$exception_list`. Exception entries contain `type`, `module`,
`value`, `mechanism`, and `stacktrace.frames`; Python frames can contain
absolute paths and source context even when local-variable capture is off.
Sanitize message values and preserve only useful code-location fields. Keep
`capture_exception_code_variables=False` and `log_captured_exceptions=False`.
Make the sanitizer catch its own errors and return `None`: released SDK behavior
and current main have differed on a failing hook, so fail-closed behavior belongs
in Canary. Never handcraft the full exception event as an alternative to SDK
capture. [Exception serialization](https://github.com/PostHog/posthog-python/blob/main/posthog/exception_utils.py),
[client filtering](https://github.com/PostHog/posthog-python/blob/main/posthog/client.py)

## Browser integration and source maps

The documented minimal extension pattern is:

```ts
import 'posthog-js/dist/exception-autocapture'
import posthog from 'posthog-js/dist/module.no-external'
```

It bundles exception support and disables remote extension loading. Do not
import a second PostHog entry point elsewhere. Explicitly disable replay,
DOM autocapture, automatic pageviews/pageleaves, dead clicks, heatmaps, and
unneeded performance capture. Capture curated flow events separately. The
official `@posthog/react` provider currently supports the default SDK import
only; Canary can use its existing error boundary and a central service instead.
The alternative slim bundle is experimental.
[Official installation variants](https://github.com/PostHog/posthog.com/blob/master/contents/docs/integrate/_snippets/install-web.mdx),
[configuration](https://posthog.com/docs/libraries/js/config)

Identify using the stable authenticated user ID and reset on signout/account
change. Send the SDK session reference with authenticated API requests, but
derive backend identity from authentication rather than trusting a supplied
distinct ID. Strip automatic URL, referrer, arbitrary error-message and content
properties before delivery. Disable console capture to avoid manuscript data.
[Identity recipe](https://github.com/PostHog/skills/blob/main/skills/posthog/all/skills/integration-react-vite/SKILL.md),
[error capture](https://posthog.com/docs/error-tracking/capture)

Vite uses the default export from `@posthog/rollup-plugin`:

```ts
posthog({
  personalApiKey: process.env.POSTHOG_API_KEY,
  projectId: process.env.POSTHOG_PROJECT_ID,
  host: process.env.POSTHOG_HOST,
  sourcemaps: {
    enabled: true,
    releaseName: 'canary-web',
    releaseVersion: release,
    deleteAfterUpload: true,
  },
})
```

The upload key is a **personal API key** with error-tracking write access,
confined to the build environment. It is not the public capture token and must
never receive a `VITE_` prefix. The documented plugin default and current source
both use `https://us.i.posthog.com`; its config passes that host to the CLI.
The ingest hostname is therefore supported for the plugin. Check that generated
chunks have the injected chunk ID and uploaded maps are removed from artifacts.
[Vite guide](https://posthog.com/docs/error-tracking/upload-source-maps/vite),
[plugin config](https://github.com/PostHog/posthog-js/blob/main/packages/plugin-utils/src/config.ts),
[CLI invocation](https://github.com/PostHog/posthog-js/blob/main/packages/plugin-utils/src/cli.ts)

At inspection, repository main declared `posthog-js` 1.434.15 and
`@posthog/rollup-plugin` 1.6.1, while npm search metadata lagged. Repository main
is not publication proof: use the package registry and generated lockfile as
the installed-version authority.
[Browser package](https://github.com/PostHog/posthog-js/blob/main/packages/browser/package.json),
[Rollup package](https://github.com/PostHog/posthog-js/blob/main/packages/rollup-plugin/package.json)

## OTLP logs and general traces

Keep standard OpenTelemetry for Canary's async spans. Install the HTTP/protobuf
exporter package `opentelemetry-exporter-otlp-proto-http` with the SDK; the
generic exporter metapackage is unnecessary. Direct cloud exports need no
collector or local database. Use the configured regional ingest host:

| Signal | Endpoint | Authentication |
| --- | --- | --- |
| General spans | `/i/v1/traces` | `Authorization: Bearer <project-token>` |
| Logs | `/i/v1/logs` | `Authorization: Bearer <project-token>` |

Use the `phc_` project token, not a personal key. Configure full signal endpoints
rather than the generic base endpoint that appends another path. The log SDK
uses `_logs` imports, `LoggerProvider`, `LoggingHandler`,
`BatchLogRecordProcessor`, and `OTLPLogExporter`. Export only sanitized structured
records; attaching an unsanitized root logger would also export third-party
exceptions, requests, and content.
[Python traces](https://posthog.com/docs/distributed-tracing/installation/python),
[Python logs](https://posthog.com/docs/logs/installation/python)

Resource attributes identify service, environment, and release. Put
`posthogDistinctId` and `sessionId` on span/log attributes for PostHog joins;
the active OTel context supplies proper log trace/span IDs. Persist validated
trace context and safe operation identifiers with durable job commands and
restore isolated context per attempt. This queue step is application work,
not a vendor recipe that happens automatically. Keep operation records and
paid-result recovery independent of telemetry.
[Log/person/session joins](https://posthog.com/docs/logs/link-session-replay),
[trace joins](https://posthog.com/docs/distributed-tracing/installation/python)

## AI observations and image generation

Use manual `$ai_generation` capture at Canary's common call boundary. Include
trace/span IDs, model/provider, latency in seconds, outcome, known token counts,
and safe image metadata. Omit prompts, tool arguments, output text, images,
artifact URLs and arbitrary provider error bodies. A generation can be observed
without exporting creative content; this intentionally reduces content-based
AI analysis. Child generations produce a pseudo-trace automatically, so there
is no need for a second complete hierarchy of explicit AI stage spans.
[Manual recipe](https://github.com/PostHog/skills/blob/main/skills/posthog/all/skills/llm-analytics-setup/references/manual-capture.md)

The official LiteLLM callback recipe exports `$ai_input` and
`$ai_output_choices`. Do not enable it alongside Canary's manual integration:
that would duplicate observations and bypass the content-free policy.
[LiteLLM recipe](https://github.com/PostHog/skills/blob/main/skills/posthog/all/skills/llm-analytics-setup/references/litellm.md)

For a provider-reported total, send `$ai_total_cost_usd` with
`$ai_cost_passthrough=True`; the current event schema says this preserves the
total without inventing input/output components. Keep unknown amounts absent
and record Canary's usage/cost status explicitly. PostHog can estimate costs
from model/token metadata; its UI totals must therefore not be mistaken for
known provider charges or charged user credits. Unknown-cost passthrough behavior
was not established by the reviewed docs. Filter operational cost reporting by
Canary's status and retain the ledger as authority.
[Current generation schema](https://github.com/PostHog/posthog/blob/master/docs/onboarding/ai-observability/_snippets/generation-event.tsx),
[Cost calculation](https://posthog.com/docs/ai-observability/calculating-costs)

## Repeatable dashboard setup

Management requests use the **app host** (`https://us.posthog.com` or
`https://eu.posthog.com`) and personal-key Bearer authentication. Create a
dashboard at `POST /api/projects/:project_id/dashboards/` with `name`,
`description`, and optional `tags`; create insights at
`POST /api/projects/:project_id/insights/` with `name`, `description`, `query`,
and `dashboards: [dashboard_id]`. Scopes are `dashboard:write` and
`insight:write`, plus read scopes for finding/reusing managed resources.
Pagination and stable ownership tags should make setup repeatable.
[Dashboard API](https://posthog.com/docs/api/dashboards),
[Insight API](https://posthog.com/docs/api/insights)

An insight query wraps its source as
`{kind: 'InsightVizNode', source: {...}}`. A trends source uses
`kind: 'TrendsQuery'`, `series` entries with `kind: 'EventsNode'`, `event`,
`name`, and `math: 'total'`, plus `trendsFilter: {}`. A funnel source uses
`kind: 'FunnelsQuery'`, ordered event series, and `funnelsFilter` with
`funnelOrderType: 'ordered'`, `funnelVizType: 'steps'`,
`funnelWindowInterval: 14`, `funnelWindowIntervalUnit: 'day'`.
Date selection is `dateRange: {date_from: '-30d'}`. Funnel definitions must use
actual successful transitions, not admission/queued events as completion.
[Official trends example](https://posthog.com/docs/product-analytics/dashboards#example-creating-an-insight),
[Query schema authority](https://github.com/PostHog/posthog/blob/master/frontend/src/queries/schema/schema-general.ts)

No vendor-account API mutations, credential changes, or live provider calls
were made for this research. Deployment credentials, actual ingestion,
source-map uploads, account feature access, and notification destinations remain
deployment verification concerns rather than research findings.

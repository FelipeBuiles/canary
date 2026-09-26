# PostHog tracing: primary-source evidence and Canary implications

Implementation follow-up: the user authorized consolidation without a separate
synthetic-journey gate. See the [current operating guide](../reference/observability.md)
for implemented behavior and remaining activation steps. This research records the
decision basis, not evidence that cloud delivery is live.

**Status: Proposed.** Research checked September 26, 2026. This is vendor
capability research for the launch consolidation decision, not evidence that
Canary has any of these integrations enabled. No account settings, application
code, or cloud resources were changed. Public documentation and published SDK
source were inspected; delivery, account access, and UI behavior remain untested.

## Finding

PostHog does have **general distributed tracing**, separate from AI traces.
The question is maturity and fit, not whether PostHog only has LLM events.
Its standard OTLP receiver accepts application spans at `/i/v1/traces`, while
`/i/v0/ai/otel` is the separate generative-AI ingestion route. The documented
general tracing UI offers waterfalls, span filtering, and correlated logs in
the span inspector. [Tracing setup](https://posthog.com/docs/distributed-tracing/start-here)

However, PostHog's own observability sales handbook calls distributed tracing
and metrics **alpha**, with endpoints potentially changing. It identifies no
span alerting, server-side tail sampling, browser/mobile tracing, profiling,
service map, synthetic monitoring, infrastructure monitoring, or built-in
on-call management. It calls errors, logs, and web vitals production-ready.
These are first-party admissions of product limits, stronger evidence than
marketing comparisons. Its advice to existing observability customers is to
retain their present tool during an alpha migration.
[Observability handbook](https://posthog.com/handbook/growth/use-case-selling/observability)

**Assessment:** a PostHog-first launch is viable if the dependable baseline is
curated events, errors, structured logs, durable job state, and independent
health checks. General tracing can enrich diagnosis without being required to
detect incidents or establish paid outcomes. A requirement for mature,
end-to-end browser-to-worker APM would favor retaining Sentry.

## What is actually shipped

| Capability | Evidence | Implication |
| --- | --- | --- |
| General OTLP spans | Canonical [distributed tracing docs](https://posthog.com/docs/distributed-tracing) describe standard OpenTelemetry clients and an HTTP receiver. | Existing OTel instrumentation has a plausible destination; do not repurpose AI event ingestion as generic APM. |
| Python native spans | [Python tracing installation](https://posthog.com/docs/distributed-tracing/installation/python) documents manual spans in `posthog>=7.58.0`, alongside an OTel alternative. | Can instrument selected operations without a separate trace SDK, but this is not automatic FastAPI/database instrumentation. |
| Published implementation | [PyPI 7.58.0](https://pypi.org/project/posthog/7.58.0/) was uploaded September 18; [7.60.1](https://pypi.org/project/posthog/7.60.1/) is the checked current release. The published wheel contains `posthog/tracing/` and tracing tests. | Native Python tracing is newly shipped, not merely documentation of a planned feature. No package was installed during research. |
| Native API stability | [Python SDK docs](https://posthog.com/docs/libraries/python#distributed-tracing) explicitly call the span API experimental and subject to changes in minor releases. | Pin and review the SDK version if choosing this route. |
| UI access | Public [tracing manifest](https://github.com/PostHog/posthog/blob/master/products/tracing/manifest.tsx) gates its product navigation entry on `FEATURE_FLAGS.TRACING`. | Published code proves implementation, not this account's entitlement or rollout status. Confirm access during the proof. |
| Python application logs | [Python logs installation](https://posthog.com/docs/logs/installation/python) uses standard Python logging plus OTel's log SDK and OTLP HTTP exporter at `/i/v1/logs`. | Native PostHog tracing does not itself eliminate OTel dependencies for this documented logging path. The docs also flag OTel Python's `_logs` API as experimental. |

The standard OTel route is a particularly good candidate for Canary because it
already has OTel spans and uses FastAPI and async work. PostHog's own Python
tracing guide recommends OTel for existing OTel setups, framework/database
auto-instrumentation, or `AsyncPosthog` users. Both routes send the same OTLP
span format. This suggests simplifying the existing provider/exporter setup
instead of automatically deleting OTel as part of deleting Langfuse.
[Python tracing installation](https://posthog.com/docs/distributed-tracing/installation/python)

## Queue and restart behavior

The native Python API supports producer/consumer span kinds and W3C
`traceparent`/`tracestate`. Its active span uses ContextVars across `await`, but
threads and forked processes need explicit parenting. `AsyncPosthog` does not
support tracing; the synchronous client does. These are useful primitives,
not automatic propagation through Canary's durable queue.
[Python SDK docs](https://posthog.com/docs/libraries/python#distributed-tracing)

Proposed queue design, independent of vendor:

1. Admit the action under an opaque `operation_id`; persist validated trace
   context and safe product context with the existing job command.
2. End the request/enqueue span when admission completes. Measure queue delay
   from durable admission and worker-start times.
3. Restore isolated context for each execution attempt. Trace provider calls,
   validation, artifact persistence, and settlement separately.
4. Record restart/recovery as a new execution attempt, preserving the operation
   identity. Do not recreate an already-submitted paid provider call to make a
   trace look complete.
5. Emit explicit outcome logs/events after durable transitions. These and the
   job/ledger/recovery records remain the fallback when trace delivery fails.

Native SDK implementation stores active spans and export queues in memory.
Finished spans are queued; shutdown discards unended spans. The documented
server timestamp policy clamps starts more than 24 hours old to receive time.
Its defaults bound pending spans and event/attribute counts. Therefore a
single open project trace spanning approvals, process restarts, and days of
inactivity is a poor model. [Native span implementation](https://github.com/PostHog/posthog-python/blob/main/posthog/tracing/_span.py),
[native pipeline](https://github.com/PostHog/posthog-python/blob/main/posthog/tracing/_pipeline.py),
[Python SDK docs](https://posthog.com/docs/libraries/python#distributed-tracing)

Neither reviewed source established how the UI handles children arriving well
after the original root, cross-day traces, or linked recovery traces. Treat
that as an explicit acceptance test. Standard OTel links are a viable modeling
primitive, but receiver compatibility does not prove PostHog renders a useful
clickable causal relationship.

Sampling also needs a deliberate choice. The native Python implementation
preserves an inherited W3C sampling flag but records/exports regardless of its
value. OTel's parent-based sampling is a better fit if trace consistency across
services is required. Keep critical outcome/error records independent of trace
sampling; per-span random dropping makes misleading partial traces.
[Native pipeline](https://github.com/PostHog/posthog-python/blob/main/posthog/tracing/_pipeline.py),
[Python SDK docs](https://posthog.com/docs/libraries/python#tracing-across-services)

## General traces, AI traces, and linking

AI Observability is an event-based tree built from `$ai_trace_id`, spans, and
generations; optional `$ai_session_id` groups multiple AI traces. Its waterfall
can show duration, nesting, and parallel work. It is suitable for a bounded
generation operation containing preparation, provider work, and validation.
It does not establish generic HTTP/database instrumentation or substitute for
the general OTLP tracing product. [AI traces](https://posthog.com/docs/ai-observability/traces)

Manual AI capture is supported, so Canary's provider adapter could emit safe
generation metadata without wrapping every provider SDK. This is a useful
option for its gateway/custom image routes. Exact image usage/cost mapping and
content suppression need provider-free contract checks before sending real
work. [Manual AI capture](https://posthog.com/docs/ai-observability/installation/manual-capture)

There is a documented **error-to-AI-trace** link: attach the same `$ai_trace_id`
to a captured exception and the issue exposes an LLM-trace button. There is no
need to send prompts or artwork to make that identity match.
[AI/error linking](https://posthog.com/docs/ai-observability/link-error-tracking)

General tracing documents **span-to-log** navigation. OTel LogRecords can carry
trace and span IDs directly. This supports using one OTel context for backend
traces and logs; merely adding an arbitrary `trace_id` string to a log message
does not establish that the receiver populates its trace fields.
[Trace explorer setup](https://posthog.com/docs/distributed-tracing/start-here),
[OTel log correlation](https://opentelemetry.io/docs/specs/otel/logs/)

PostHog person/session joins use `posthogDistinctId` and `sessionId` on logs
and general spans. Replay is optional: person linking works alone. Canary
should derive the authenticated identity itself, preserve a validated session
reference if needed, and avoid trusting a browser-supplied distinct ID as an
authorization identity.
[Log linking](https://posthog.com/docs/logs/link-session-replay),
[Python tracing joins](https://posthog.com/docs/distributed-tracing/installation/python)

**Not established:** that an AI trace and general OTLP trace sharing an ID
automatically become one tree, or that all general trace/error links work
without explicit properties. Design a shared `operation_id` across signals,
then prove the actual navigation. Avoid two full duplicate trees for every
stage solely to populate two product screens.

## Privacy and failure behavior

The ordinary Python `before_send` hook is documented to send the original event
if the hook raises. The native tracing `before_span_send` hook instead drops
the span on failure. Thus a generic scrub callback is not sufficient protection
for creative content. Construct allowlisted observations before invoking the
SDK, catch redaction failures and return `None`, and test hooks separately for
events, exceptions, spans, and logs. Native exception span events can include
server file paths in stack traces.
[Event filtering](https://posthog.com/docs/libraries/python#filtering-or-modifying-events-before-sending),
[span filtering implementation](https://github.com/PostHog/posthog-python/blob/main/posthog/tracing/_before_span_send.py)

This design can preserve the prior proposal's content-free collection. It also
means prompt inspection, automatic trace sentiment, and some AI trace-analysis
features will intentionally have less evidence available. Consolidation should
be justified by operational context and outcome learning, not by features that
require exporting manuscripts or art.

## Alerts and operational completeness

PostHog log alerts support filtered counts, thresholds, time windows,
consecutive-check rules, cooldowns, and Slack/email/webhook destinations. They
can detect a known failure pattern or missing expected heartbeat logs. Alerts
that fail five consecutive evaluation checks become broken and stop evaluating
until reset; this deserves a runbook check. [Log alerts](https://posthog.com/docs/logs/alerts)

These are not external synthetic probes. Canary still needs its existing
platform health/metrics and an independently scheduled operation monitor to
detect a dead process, old queued job, or ambiguous paid outcome. A process
cannot reliably report its own death. Preserve a stdout fallback and avoid
making job success depend on a telemetry network call.

## Provider-free proof before removing Sentry

- Confirm this PostHog project can view errors, logs, and general traces;
  establish retention, alpha terms, and eventual pricing rather than treating
  free alpha ingestion as a permanent price.
- Run one synthetic FastAPI request that enqueues a durable job, returns, and
  later executes after a worker restart. Capture queue delay, parallel child
  operations, a handled failure, saved-result evidence, and settlement status.
- From one operation reference, retrieve the right user, job, logs, error,
  general trace, and optional AI trace. Prove isolation between concurrent jobs.
- Check the late-child, delayed-job, recovery-attempt, and trace-link displays.
  If they are unusable, judge whether logs plus durable state satisfy launch
  support; do not claim mature APM coverage.
- Verify an exception and a stalled-job condition each deliver one actionable
  alert. Demonstrate external monitoring still works if Canary stops emitting.
- Inject exporter failures, queue saturation, malformed context, sensitive
  marker fields, and failing scrub hooks. Confirm no creative content leaks,
  no paid action repeats, and application outcomes do not change.

**Decision boundary:** promote PostHog to the single application telemetry
vendor after these checks pass. Keep Sentry if the required debugging workflow
depends on mature tracing or the proof exposes unresolved privacy, delivery,
or alerting gaps. Retain the application database, recovery artifacts, and
platform monitoring under either choice.

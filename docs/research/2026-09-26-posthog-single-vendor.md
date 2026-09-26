# PostHog as Canary's single observability vendor

Implementation follow-up: the user authorized consolidation without a separate
synthetic-journey gate. See the [current operating guide](../reference/observability.md)
for implemented behavior and remaining activation steps. This research records the
decision basis, not evidence that cloud delivery is live.

**Status: Proposed decision, September 26, 2026.** Follow-up research to the
[telemetry overhaul](2026-09-26-observability-simplification.md). This note refines
the earlier Sentry-first recommendation using newly verified tracing and SDK
documentation. No account was provisioned, live data inspected, application code
changed, or production integration tested.

## Verdict

**PostHog is viable as Canary's primary product analytics and application
observability vendor. Given the explicit preference to simplify, I recommend
PostHog-first, subject to a short integration proof before retiring Sentry.**

The important qualification is that its general distributed tracing is still
alpha. Use established product events, errors, logs, and AI observations as the
launch operating foundation; treat the new trace explorer as useful diagnostic
coverage whose loss cannot disable incident detection or paid-work recovery.
If dependable mature APM is a launch requirement, retain the Sentry option.

“Single vendor” here means one hosted analysis/debugging destination. Canary
still needs its database, paid-result files, Fly platform metrics/stdout, and an
independently running availability monitor. PostHog is not a replacement for
those authorities. It also does not collapse every signal into one SDK call.

The material change from the previous research is that **general OTLP tracing
is documented and Python support exists**. It is no longer merely a possible
roadmap feature. The question is whether its current limitations are acceptable
for this specific application. See [tracing evidence](2026-09-26-posthog-tracing-evidence.md)
and [PostHog distributed tracing](https://posthog.com/docs/distributed-tracing).

## Capability and fit

| Canary need | Evidence and remaining work | Assessment |
| --- | --- | --- |
| Funnels, paths, return behavior | Existing PostHog analytics fits multi-session authors; retain the explicit events and cohort definitions in the [learning plan](2026-09-26-launch-learning-system.md). | Strong fit. |
| React exceptions | SDK exception capture and React error boundaries are documented; Vite has a source-map upload plugin with release/chunk identification. Test the deployed minified bundle. [Capture](https://posthog.com/docs/error-tracking/capture), [Vite source maps](https://posthog.com/docs/error-tracking/upload-source-maps/vite) | Viable Sentry replacement for this browser app. |
| FastAPI and worker exceptions | Python capture exists. The official setup explains that framework error handlers can bypass global exception hooks, so FastAPI needs explicit integration. Handled job failures also need observation at their durable outcome boundary. [Python installation source](https://github.com/PostHog/posthog/blob/master/docs/onboarding/error-tracking/python.tsx) | Viable, with implementation work. |
| Issue grouping and triage | Automatic grouping, custom fingerprints, merge/group rules, affected-user context, and release linkage are documented. Verify grouping with provider refusals versus bugs rather than assuming identical Sentry behavior. [Grouping](https://posthog.com/docs/error-tracking/grouping-issues), [Releases](https://posthog.com/docs/error-tracking/link-releases) | Enough documented capability for a small launch; usability remains to test. |
| Searchable production logs | OTLP log ingestion, filtering, person linkage, and alerts are documented. `posthogDistinctId` or a configured attribute joins logs to a person. [Logs](https://posthog.com/docs/logs), [People](https://posthog.com/docs/data/persons) | Strong fit; removes routine local-file hunting. |
| General execution traces | Standard OTLP receiver and backend SDKs exist. General tracing is alpha; the new native Python span API is experimental. [Overview](https://posthog.com/docs/distributed-tracing), [Python SDK](https://posthog.com/docs/libraries/python#distributed-tracing) | Viable with explicit maturity risk and a tested alternative. |
| Durable queue / page generation | No SDK automatically reconstructs Canary's persisted job context, frozen requests, or paid-result lifecycle. This is work required under either vendor. | Must prove queue/restart correlation; not a reason by itself to reject PostHog. |
| Text, image, OCR, and costs | Manual AI events support trace/span relationships and caller-supplied costs. Image/gateway coverage must be explicitly mapped, including unknown cost. [Manual capture](https://posthog.com/docs/ai-observability/installation/manual-capture), [Cost calculation](https://posthog.com/docs/ai-observability/calculating-costs) | Good replacement for Canary's current Langfuse observation use; not automatic image-quality evaluation. |
| Alerts | Issue-created/reopened, spike, log, and insight alerts exist. Error alerts support chat/webhooks; trend alerts can send email. [Error alerts](https://posthog.com/docs/error-tracking/alerts), [Log alerts](https://posthog.com/docs/logs/alerts) | Adequate if launch incidents use errors/logs/domain monitoring. |
| Host health, uptime, profiling | PostHog's own comparison identifies absent infrastructure/synthetic monitoring, profiling, and on-call management. [Official scope/limitations](https://github.com/PostHog/posthog.com/blob/master/contents/handbook/growth/use-case-selling/observability.md) | Keep Fly and the existing independent monitor. |
| Feedback and learning | Surveys can join product identity; notebooks/insights support analysis. Keep free-text feedback privately in Canary as already proposed, export only safe metadata. | One analysis surface without making customer prose another telemetry payload. |

## Pros that matter for a sole developer

**One investigation context.** A frustrating Pages experience can lead from an
author's journey to an exception, related logs, and model-call timing. Less
identity mapping between tools means fewer places to configure account resets,
release names, saved searches, and staff access. This benefit depends on
correct correlation; sending records to one hostname alone does not establish it.

**A meaningful reduction in infrastructure.** After replacement validation,
remove the six optional Langfuse services, its bespoke exporter, and Sentry's
application SDK/configuration paths. Retain one PostHog project and one coherent
server observability bootstrap. No local trace collector/database is necessary
for direct OTLP export.

**The strengths align with launch questions.** The key questions are which
authors get blocked, which phase failed, which provider call was slow, and
whether output/credits are safe. Deep host profiling and complex service maps
are less central for the current one-Machine application. That is a project-fit
judgment, not a claim that the missing features never matter.

**Low initial cash cost and an exit route.** Launch volumes can fit the published
free allowances. Standard OTLP logs/traces and first-party business records
reduce migration cost if another destination is needed later. PostHog-specific
events, dashboards, identity semantics, and alert configuration remain vendor
coupling; open ingestion does not make the entire system portable.

## Cons and their practical impact

**Tracing maturity is the principal risk.** The native Python span API requires
7.58.0 or later and is explicitly experimental; `AsyncPosthog` does not support
it. General tracing and metrics are alpha. The detailed source/release checks
are in the [evidence note](2026-09-26-posthog-tracing-evidence.md). Prefer ordinary
OpenTelemetry for Python logs/traces, pin versions, and put export configuration
behind one small boundary. This avoids relying on a brand-new vendor span API,
although the receiving product remains alpha.

**Some APM conveniences are missing.** The official scope page reports no
span-based alerts, server-side tail sampling, browser/mobile tracing, or rendered
service map. Canary should alert from explicit failure/slow-operation log
records and its independent domain monitor. Browser errors and product events
remain available, but should not be described as a complete browser-to-provider
waterfall. [Official limitations](https://github.com/PostHog/posthog.com/blob/master/contents/handbook/growth/use-case-selling/observability.md)

**One vendor still has multiple data paths.** Product and exception events use
PostHog SDK/event ingestion; AI observations use AI event semantics; general
logs/traces use OTLP. These have different enrichment, retention, redaction,
limits, and failure behavior. The AI trace tree and the general distributed
trace tree are distinct views. Shared IDs enable correlation but do not prove
an automatic combined waterfall or guarantee that one ingestion creates both.

**Capture needs more deliberate wiring than the existing Sentry bootstrap.**
Install the browser error path, integrate FastAPI and worker handling, wire
source maps into CI, and preserve release and account scoping. Do not blindly
copy example handlers that return `str(exc)` to users; Canary's existing safe
HTTP/error contracts stay authoritative.

**Shared outage and quota exposure.** If PostHog is unavailable, product analysis
and operational exploration disappear together. Keep JSON stdout, durable
operation summaries, and availability monitoring independent. Free or configured
billing limits discard excess events; lack of observations cannot mean lack of
activity. Test rate limits, backpressure, and dashboard freshness.

**Privacy work remains substantial.** Replay, prompts/completions, code locals,
arbitrary exception text, and request/response bodies stay off. A single vendor
reduces processor administration but concentrates the information it receives.
The Python SDK event `before_send` hook fails open if its callback raises;
construct allowlisted payloads before capture and make scrub failures drop the
event. See the [source evidence](2026-09-26-posthog-tracing-evidence.md).
Event/person deletion documentation does not by itself prove deletion semantics
for every OTLP log/span store. Verify those separately before promising
account-level erasure across all signals. Operational attributes can use opaque
operation IDs without persistent person linkage where necessary.

## Costs and retention

Current published monthly free allowances relevant to this design:

| Product | Free allowance | Important qualification |
| --- | --- | --- |
| Product analytics | 1 million events | Free project event retention is one year. |
| Error tracking | 100,000 exceptions | An exception storm still needs suppression/rate limits. |
| AI observability | 100,000 events | Count spans/trace records as well as generations when estimating emitted AI events. |
| Logs | 10 GB ingested | Default retention is 14 days. |
| General distributed traces | Alpha terms | Confirm account access, current limits, retention, and future pricing; do not assume the AI allowance also covers OTLP spans. |

The first four allowances and quota-drop behavior come from
[current pricing](https://posthog.com/pricing). Older launch posts mentioning
50 GB of free logs should not be used for this budget. The dedicated
[log pricing guide](https://posthog.com/docs/logs/pricing) now supports custom
retention at $0.05 per ingested GB per retained month, applied to new logs.
Main pricing still summarizes the 14-day default. Use the dedicated guide and
actual account settings when enabling extended retention.

Illustrative volume, not a traffic forecast: 100 authors × 500 curated product
events = 50,000 events; 100 authors × 100 provider calls × 5 AI records per call
= 50,000 AI records. These fit the respective headline allowances. By contrast,
one 1 KB log each second is approximately 2.6 GB per 30 days; ten each second is
approximately 26 GB. Polling/verbose gateway logs can dominate cost long before
user counts are large. General OTLP spans require their own volume estimate.

Start with explicit per-product budgets and delivery monitoring. A $0 cap
controls charges, not completeness. Preserve diagnostics needed for critical
incidents outside vendor availability. Avoid a warehouse sync of manuscripts,
full usage rows, or feedback simply because one vendor supports it.

## Recommended implementation shape

Use a **PostHog-first deployment with two export mechanisms**:

1. PostHog browser/Python SDKs for errors and curated events. Continue sending
   authoritative product outcomes through the existing authenticated first-party
   pipeline; one owner emits each event. A minimal browser SDK replaces Sentry's
   error role, with replay/autocapture/automatic page URLs disabled and safe
   exception processing. This is a justified change from the earlier
   server-only analytics SDK suggestion.
2. Standard OTel Python instrumentation and batched exporters for structured
   logs and general spans, sent directly to PostHog's regional OTLP endpoints.
   Reuse and simplify the existing OTel bootstrap rather than remove it in favor
   of Sentry native spans. Add the required dependencies to the production image.

For AI observations, emit metadata-only `$ai_generation` records from the
central AI lifecycle after recording the actual outcome. Record the configured
alias, actual provider model, duration, image/token counts, and known cost
provenance. A gateway-supplied total can use `$ai_cost_passthrough` with
`$ai_total_cost_usd`, documented in the
[generation schema](https://github.com/PostHog/posthog/blob/master/docs/onboarding/ai-observability/_snippets/generation-event.tsx).
Verify unknown-cost behavior: omitted cost must not silently become an inferred
zero or a vendor estimate presented as settled provider cost. Keep a separate
`cost_status` and use Canary's ledger for financial decisions.

Use the same opaque operation and provider-call IDs on errors, logs, spans,
product outcomes and AI records. Explicitly map OTel and AI trace/span IDs;
capture only the small subset of AI span events needed for that view. Avoid
duplicating every general span as an AI event. Preserve W3C context across
admission and the durable worker boundary without changing creative request
hashes or paid-action idempotency.

Correlation must survive thread offloads, concurrent users, delayed execution,
and restart. Traces end; projects continue. Never hold a span across a human
approval wait or manufacture successful terminal spans after a crash. Keep the
existing operation-detail backoffice design as the source of current truth,
with links into PostHog and explicit missing/expired telemetry states.

Alert from domain outcomes and selected logs/errors. A monitor outside the
application must still detect a dead Machine or worker. The desired notification
channel and delivery semantics should be tested; no new alert or message is
enabled during this research.

## A decisive proof, not an open-ended migration

Timebox a **1–2 developer-day synthetic integration proof** before committing
the full overhaul. This is a planning estimate. Use an isolated test project
or a clearly segregated test environment under the actual account entitlement;
do not send customer content or perform paid generation.

| Acceptance check | Evidence required |
| --- | --- |
| Browser error | Deployed/minified React exception resolves to the correct source and release, with no creative content or credentials. |
| API and worker failure | Expected error grouping, exactly one intended issue capture per failure, account isolation, actionable safe context. |
| Queue continuation | Enqueue, stop/restart before execution, then run a fake provider: original operation is findable and related logs/spans remain correctly associated. No paid operation is retried for telemetry. |
| Text/image/OCR outcomes | Success, refusal, timeout with unknown outcome, and art-saved/OCR-failed remain distinct. Known cost agrees with the fixture; unknown cost remains visibly unknown. |
| Cross-product investigation | Starting with a support reference, reach the relevant journey, error, log and trace in a few clicks or one saved query. Document any manual join; no promised automatic link left untested. |
| Alert and silence detection | Receive one test alert in the chosen channel; demonstrate a failed/stalled domain operation and application unavailability are detected independently of successful trace export. |
| Privacy and lifecycle | Inspect actual event, log and span payloads with seeded sensitive strings; verify opt-out/identity reset and each signal's deletion/retention behavior. Optional analytics choices must not be bypassed through diagnostic capture. |
| Exporter failure | Simulate unavailable ingestion and rate limiting: bounded memory/shutdown, no application failure, no lost recovery state, no provider resubmission. |

**Go:** these checks pass, trace alpha limitations are acceptable, and common
incidents remain diagnosable from logs/errors/authoritative state if traces are
missing. Complete migration, then remove Sentry and Langfuse export paths.

**Fallback:** if mandatory privacy, alert delivery, queue correlation, or useful
trace display fails, retain Sentry for operations and PostHog for product
analytics. If only an optional APM convenience is absent, do not add another
vendor automatically. Limit any dual capture to synthetic/parity verification;
do not operate permanent duplicate telemetry pipelines.

This changes the preferred direction from **Sentry-first because PostHog tracing
was unverified** to **PostHog-first because the required pieces are documented,
with a concrete acceptance gate for their integration and alpha risk**. The
evidence supports a viable architecture, not a claim that Canary has already
been validated on PostHog.

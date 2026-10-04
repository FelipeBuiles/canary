# PostHog investigation and AI observability handoff

Status: Historical — investigation snapshot, October 3, 2026 (America/Toronto).
Implementation proposals below are unapproved. Recheck the relevant code and
live configuration before acting; this document does not replace current contracts.

## Objective and authorization

Scenewright uses PostHog project **630262**, US region. The organization still
uses **Canary**; the project metadata returned **Default project**, so use the
ID rather than assuming its displayed name. The user sees $50,000 startup credits.

The original request covered AI observability, user journeys, debugging,
contextual first-comic feedback, safe model/prompt rollouts, experiment viability,
startup-credit terms and billing safeguards. The user then emphasized:

> “I'm especially interested in AI usage traces being useful enough to make decisions.
> Even capturing traces for local dev usage to compare token usage, response quality, time... all that stuff”

**Authorization remains investigation and recommendations only.** The user
explicitly said to ask before implementing code or changing live settings.
They subsequently authorized writing this summary, not implementation. The last
proposal awaiting an answer was the first implementation slice: trace structure,
version metadata, and clearer timing/token measurements with existing masking.
Ask for that approval if a new session has no subsequent authorization.

Work in the shared checkout and preserve extensive unrelated uncommitted edits.
Do not create a routine worktree, start/restart development servers, run paid
generation, consume subscription generation allowances, or change live PostHog
settings as part of reviewing this handoff.

## Evidence scope and limitations

The main event audit used the fixed UTC window
`2026-09-26 00:00:00 <= timestamp < 2026-10-03 03:00:00`
(through October 2 evening in Toronto). The illustrative local trace was inspected
in an October 2–3 UTC window. This is a snapshot, not a current traffic forecast.

Evidence came from repository code, focused tests, the native PostHog connector,
read-only billing UI inspection, a masked replay sample, and official PostHog
documentation. No application code or live settings were changed. Only this
handoff was added afterward.

The data catalog contained no approved metrics. Custom SQL counts below are
investigation measures, not canonical business metrics. Anonymous browser
identities can reset: person counts are not necessarily counts of human visitors.
Small samples cannot establish provider reliability or comparative model quality.

## What exists and is working

- [Current operating guide](../reference/observability.md): one PostHog event
  client plus direct HTTP OpenTelemetry export; no local Langfuse service or
  collector is required. Events, logs and distributed traces are arriving.
- [Launch pulse](https://us.posthog.com/project/630262/dashboard/2145123) and
  [Pipeline health & cost](https://us.posthog.com/project/630262/dashboard/2145124)
  already cover acquisition, activation, stage outcomes, spend and friction.
  Production views exclude development and the Internal / Test users cohort.
- Durable product-event forwarding, account-created recovery and purchase-event
  outbox code exist. The account and purchase migrations are recorded as deployed
  in the existing documentation; no new production purchase was observed in the
  launch audit, so this is not end-to-end evidence of a new purchase.
- AI events record model, stage, feature, duration, provider/funding, tokens,
  error class and cost confidence. Known cache reads/writes are retained and
  input totals are explicitly cache-inclusive.
- First-party `ai_usage_events`, ledger, reservations, operation journal and
  provider recovery remain the financial authorities. PostHog delivery is
  best effort, with bounded queues and shutdown drains.
- Backend/browser exception capture and browser source-map integration exist.
  The project has four error issues: two Plan validation issues, one Style
  ValueError issue and one browser EvalError issue. Successful map upload does
  not itself prove deployed exception symbolication.
- Production replay now works. At least ten non-internal production recordings
  were returned for October 2. A replay linked to a browser error showed masked
  text and blocked images. Earlier production replay was blocked by CSP access
  to the regional assets host; the existing reference records the October 2 fix.
- Private feedback storage/API/UI exists, including RLS and idempotent receipts.
  Feedback text stays in Supabase; PostHog receives metadata. Rating support
  exists but is not used by the current feedback form.
- Local launchers label browser/backend events `development`, set a release
  identifier, and inherit configured public ingestion settings. Local capture
  is already active; detailed local files require `CANARY_LOCAL_DIAGNOSTICS=true`.

Privacy is deliberate: no raw manuscripts, prompts, generated text, image bodies
or reference images in AI telemetry. Replay masks all text/inputs and blocks
images, media, SVG/canvas and embedded content; a second serialization scrubber
removes unsafe attributes, URLs and plugin frames. Preserve both boundaries.
The project discards client IP data and retains replay for 30 days. Console-related
cloud settings do not override the client scrubber's restrictions.

## AI traces: the highest-value gap

### Local development already supplies useful volume

There were **909 development AI calls across 515 trace IDs**; 907 carried input
and output token fields. Production had **133 calls across 51 trace IDs**; 124
carried token fields. Presence is not proof of complete usage: some image calls
have zero/incomplete token coverage, and failed calls may have no usage.

Neither environment's AI events carried `$ai_parent_id` or `prompt_version`.
Production AI events all had project/job IDs but none had run ID, attempt ID,
prompt version or browser session ID. These fields are partly allowlisted in the
backend but are not propagated to the AI observations. Existing OpenTelemetry
request/worker/stage spans have parent links; the **AI Observability view** is
currently a flat grouping of calls, not that logical task hierarchy.

One [recent local trace](https://us.posthog.com/project/630262/ai-observability/traces/2838fa02d6874db0a7ebc7e0a8bbd658)
contained 20 calls, **407,235 input tokens and 37,304 output tokens**. Eight
`extract.book_map_digest` calls accounted for **207,202 input tokens (~51%)**.
This is a concrete optimization candidate, not proof those calls are wasteful:
no output-quality comparison was performed. The trace also contains Extract
and Brief calls, so it is not a single provider request.

PostHog showed about **$0.059** for this Codex subscription trace. Scenewright's
records correctly mark all its monetary costs unknown. PostHog inferred a
catalog estimate; do not call that actual spend or treat unknown as zero.
The existing `_api_equivalent_cost` helper can support a separately labeled
estimate, but runtime controls, usage coverage and pricing must still be checked.

### Why present traces cannot yet settle model/prompt decisions

1. **Success is incomplete.** Provider completion can precede schema validation,
   deterministic repair, semantic rejection or another paid attempt. Existing
   structured-call code accumulates usage across attempts, but those relationships
   and validation outcomes are not explicit in AI traces.
2. **Comparisons are not reproducible.** No prompt version, fixture/case version,
   schema version for the requested output, or frozen comparison configuration.
   Local release IDs identify a launcher session, not a reproducible snapshot of
   dirty/untracked source. Some controls and request fingerprints already exist
   privately in compact usage projections.
3. **Timing conflates different causes.** AI latency starts before usage-row
   insertion/admission/runtime work. It can include setup/queue time. Streaming
   first content/reasoning is logged internally but not exported as per-call
   timing fields. Runtime execution elapsed time exists privately for some routes.
   Do not use summed call durations as wall-clock completion time when work overlaps.
4. **Token/cost semantics need more detail.** Reasoning tokens are extracted for
   metrics but not carried by `UsageRecord` into each AI event. Fallback estimates,
   cache-inclusive totals, unavailable image-tool usage and subscription funding
   must stay distinguishable. Reasoning/cache subtotals must not be double-counted.
5. **Quality evidence is missing.** No rating/rubric/evaluation result is attached
   to the exact artifact revision. Schema validity alone does not establish story
   fidelity, continuity, readability or image quality.
6. **Provider attribution is sometimes transport-level.** Production image events
   can say `litellm`, rather than the actual leaf provider/route. Retry/fallback
   provenance, including absorbed ambiguous-attempt cost, is not fully exposed.

### Proposed first implementation slice — approval required

Estimate **2–3 focused engineering days**, subject to current diffs and scope.

- Use the existing request/worker/stage context to emit a named logical task
  hierarchy, with run/stage attempt IDs, per-call attempt identity and parent IDs.
  Include validation, local repair, retries/fallbacks and final task outcomes.
  Keep `StageRuntime` as lifecycle authority; do not create a competing pipeline.
- Record static prompt/template version or hash, output-schema hash/version,
  resolved model and provider route, relevant controls, and reproducible config
  fingerprint. For comparison cases, use opaque fixture/case IDs and locally
  retained input fingerprints; do not upload prompt bodies, source text or paths.
- Split queue/admission, setup, provider execution, first-content and final task
  elapsed time where observable. Missing measurements remain missing, not zero.
- Preserve reported/estimated/unavailable token and cost coverage, cache totals,
  funding source and reasoning usage. Add an explicitly labeled API-equivalent
  estimate only where configuration and usage support it.
- Correlate metadata-only failure/validation outcomes and artifact revision IDs.
  Keep telemetry best effort; do not let an export failure alter paid execution.

Acceptance: a provider-free synthetic run yields a navigable task/attempt tree;
validation rejection and repair remain distinguishable from provider success;
all known attempts contribute to totals; unknown costs stay unknown; timing
distinguishes queueing from execution; no prose, secrets, images or raw paths
escape the privacy allowlists. Verify ingestion with already-authorized future
dev work rather than initiating generation merely to populate a dashboard.

### Proposed second slice: local comparison and quality workflow

Estimate **2–3 additional days**. Start with a small representative set of owned
or synthetic cases. Compare baseline/candidate on the same inputs and controls,
retain all failures, and review final artifacts without knowing the variant when
practical. Show sample counts, per-case differences and variability.

Measure tokens/cost and elapsed time **through a usable result**, including repairs
and failed attempts. Report provider-call reliability, validation success and
accepted task completion separately. Ordinary development traces discover
hotspots but are not controlled benchmarks when their inputs differ.

Run existing validators locally and export only bounded results/score metadata.
Add a short human rubric: source coverage, canonical-copy fidelity, character
continuity, pacing, readability and visual quality as applicable. Retain rubric
version, evaluator type, result and exact artifact revision. Reuse the existing
provider-free [image comparison tool](../../scripts/compare_image_fidelity.py)
for source crops and reading-size review. Viewing masked replay cannot grade art.

PostHog supports code-based and LLM-judge evaluations. Its judge sends captured
input/output to a model and uses a provider API key; current metadata-only events
cannot support a meaningful content judge. Do not enable broad raw-content
capture to make it work. Start with local checks/human review; consider explicitly
approved synthetic/owned fixtures and a bounded judge budget later.
[Official evaluation documentation](https://posthog.com/docs/ai-evals).

## Production completion, cost and debugging

After excluding the currently marked internal account, the audit found **39 AI
calls from one account**: 17 reported text costs, 21 estimated image costs, and
one failed image call with unknown cost. Known attributable amounts totaled about
$0.83; this mixes reported and estimated values and is not a final settled bill.
This sample is too small to rank providers.

Record explicit generated, reviewed/accepted, Finish-ready and exported outcomes.
A generation start, page-ready event, review checkpoint, and complete comic are
different milestones. Attribute the full edition's calls, retries, failures and
shared Style/Cast allocation. Provide two distinct measures:

- **Cost of a completed edition:** all attributable attempts needed for its final
  output, with an explicit shared-asset allocation policy and unknown-usage count.
- **Blended burn per completed edition:** total generation spend including failed
  and abandoned work divided by completed editions in a defined cohort/window.

Current daily AI spend divided by pages drawn is not either measure. A durable
metadata export/outbox may be needed if completeness matters: current AI capture
can be dropped, while first-party usage/recovery is authoritative. Avoid coupling
financial settlement to PostHog availability.

Debugging correlation is uneven: all six sampled web exceptions had session IDs;
15 backend exceptions lacked job IDs, and only three had operation/trace/project
context. Propagate safe run/job/attempt/project/trace IDs and an optional browser
session correlation through the existing worker boundaries. Add terminal and
stalled-generation checks using authoritative job state/heartbeats, not just
absence of telemetry. Preserve redacted error messages and replay masking.

The native insight-alert and log-alert lists were empty. The error-alert listing
returned an unrelated GeoIP transformation, so its status was **not verified**;
inspect the live UI before claiming no error alerts exist.

## Journeys, feedback and rollouts

The Internal / Test users cohort is **595305**, based on
`$internal_or_test_user = true`; it contained one person at audit time. Verify
`CANARY_INTERNAL_ACCOUNT_IDS` covers all staff/test accounts. For retroactive
SQL exclusion, use current persons/cohort membership; person-on-events is enabled
and event-time flags can miss earlier activity by a later-marked account.

In the non-internal production sample there were 217 pageviews across 124 person
identities, four project-created events across three persons, five stage starts
and five successful/checkpoint outcomes from one account, and one Plan credit
block before stage start. There were **no observed external page-ready,
output-accepted, export or new purchase events** in this window. Seven
account-created events comprised four trigger signups since October 1 and three
legacy events with null capture method: do not report seven new signups.

Define signup → first complete comic → export/share → purchase → return use using
explicit completion events and account identity. Distinguish returning to the site
from completing another comic; purchases can occur before completion, so also
measure those paths rather than assuming one strict commercial ordering.

No native surveys, flags or experiments existed. Surveys are disabled in the SDK,
and the event allowlist would require deliberate survey integration. Prefer a
once-per-account, short first-comic prompt: “Did this turn out as you hoped?” plus
optional private feedback. Trigger after the actual completion milestone and
avoid interrupting generation or collecting manuscript excerpts.

Evaluate model/prompt flags on the server with stable account assignment. Freeze
the resolved variant/version on a new run or Draw edition. Quick rollback should
change future assignments without silently changing existing editions, profiles
or artifacts; keep configuration fallback and a kill switch.

Traffic is not sufficient for credible conversion experiments yet. For scale
only, a hypothetical 20%→30% conversion lift needs roughly 294 eligible users per
arm at 80% power and a two-sided 5% threshold; those are not measured baselines.
Use controlled local cases, human review and small operational rollouts first.

## Startup credits and billing safeguards

Billing UI showed **$50,000 available credits**, a startup plan and $0 current bill
for the October 2–November 2 period. Usage reporting is delayed; exact grant
expiry was not visible and remains to be confirmed from the account/grant.
Published terms describe a 12-month credit period. Since September 14, 2026,
published exclusions include **Inbox, PostHog AI, Replay Vision, Desktop and the
Slack app**, plus applicable optional services. Core AI Observability is distinct
from PostHog AI. Credits do not pay Scenewright's model-provider bills or judge
calls made using a provider key. Recheck [startup terms](https://posthog.com/startups)
before changing billing.

The account's Product Analytics cap was gone, but its UI still offered **Set
billing limit**. Do not claim PostHog globally removed the limit capability.
Analytics, replay, AI Observability, errors, logs, flags, surveys and several
other core products were uncapped. Excluded products had nonzero defaults:
PostHog AI $150, Replay Vision $50, Inbox $150 and Desktop $100 monthly.

Suggested initial limits, **not applied**: Product Analytics $25, Replay $25,
AI Observability $25, Error Tracking $10, Logs $10 and Feature Flags $5/month;
Surveys and unused/excluded products $0 of paid usage initially. Total core
headroom: $100/month. Verify each product's limit/free-tier semantics in the UI.
Review usage after normal dev activity, route billing emails to an active owner,
confirm grant expiry, and maintain separate provider budgets. A hard ingestion
cap can permanently lose observability data; pick limits with that tradeoff in
mind. Do not spend credits simply because they are available.

## Priority and effort

| Order | Proposed work | Indicative effort | Benefit now |
| --- | --- | --- | --- |
| 0 | Confirm grant expiry and set reviewed billing safeguards | Half a day | Prevent excluded-product charges and uncontrolled ingestion |
| 1 | AI task/attempt hierarchy, versions, timing and usage semantics | 2–3 days | Make ongoing local dev traces useful for decisions |
| 2 | Local paired comparisons and quality review | 2–3 days | Choose models/prompts using actual task quality |
| 3 | Completion/full-cost attribution and debugging correlation | 3–5 days | Explain cost per usable comic and diagnose failures |
| 4 | Correct journey/cohort definitions and completion/export/share events | 1–2 days | Learn from the first external authors |
| 5 | Contextual first-comic feedback | 1–2 days | Qualitative evidence with little traffic |
| 6 | Server-side model/prompt flags and rollback | 2–3 days | Bound future rollout risk |
| Later | Production conversion experiments and optional content judges | Reassess | Requires sufficient eligible traffic or explicit fixture/budget scope |

These are rough sequencing estimates, not a commitment; slices share work and
current concurrent changes may alter them. Avoid building all products at once.

## Code entry points and verification

Paths below are relative to `novel_to_comic/src/novel_to_comic/` unless stated:

- `server/telemetry.py`: allowlists, metadata-only AI events, trace IDs, costs,
  best-effort SDK/OTLP capture.
- `ai/context.py`: AI request context, streaming/execution observers.
- `ai/client.py`, `ai/finalisation.py`, `usage.py`: usage persistence, runtime
  routing, streaming, estimates, cancellation/failure finalization.
- `ai/usage_payloads.py`: compact private controls, schemas and runtime metadata.
- `ai/codex_runtime.py`, `ai/claude_runtime.py`: execution and usage coverage.
- `clients/structured_call.py`: validation, deterministic repair, retry usage.
- `image_route_fallback.py`: OpenAI-first Sunburst's approved single FAL fallback;
  absorbed attempt IDs/cost stay visible. Do not extend ambiguous paid retries.
- `stage_runtime.py`, `server/routers/pipeline.py`, `server/lifecycle_events.py`:
  authoritative lifecycle, run/attempt IDs, worker and product-event boundaries.
- `server/routers/feedback.py`, repository-root `web/src/telemetry.ts`:
  private feedback and browser/event/replay privacy contracts.
- Repository-root `scripts/compare_image_fidelity.py`: existing local review tool.
- [Feedback migration](../migrations/2026-09-26-posthog-feedback.sql),
  [account outbox](../migrations/2026-09-30-account-created-outbox.sql),
  [purchase outbox](../migrations/2026-09-30-purchase-event-outbox.sql).

During the investigation, **36 focused backend tests** passed across
`test_posthog.py`, `test_lifecycle_events.py` and `test_feedback.py`, and **22
frontend telemetry tests** passed. They verify contracts, not provider quality,
live billing, deployed version or durable end-to-end ingestion. No build or
provider calls were needed.

After approved code changes, start with focused backend tests for the touched
area, particularly PostHog, AI client, structured-call usage, usage payloads,
observability and stage runtime. Test nested context across concurrent workers,
failure/cancellation, retry accounting, cache semantics and privacy leakage with
fake providers. Use frontend tests/build/lint only if frontend source changes.
Run `python3 scripts/check_docs_reliability.py` for documentation changes.

For live reinspection, prefer the PostHog connector: discover the relevant skill
with `learn -s`, read it, and inspect a tool's current schema with `info` before
calling it. Consult the governed metric catalog before deriving measures. Set
explicit time bounds and discover event/property schemas; do not dump property
bags or content. Use trace `detail: "summary"` for metadata-only inspection.
Heavy content is stored in `posthog.ai_events`, not ordinary event properties,
so empty ordinary properties do not establish that content was never captured.
The initial production audit checked the dedicated table and found no nonempty
input/output payloads. Native recording tools found replay even though a SQL
session-recording metadata query was empty; prefer the native evidence.

Several statements in the current observability reference predate this snapshot
(including free-plan status and unverified production traffic). After authorized
implementation and fresh verification, update that reference with settled
contracts/evidence and retire this handoff when its useful findings are captured.

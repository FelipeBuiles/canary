# Provider fallbacks for fixed model choices

**Status: Image fallback implemented (2026-09-28); text fallback on hold.**
Sunburst Draw runs OpenAI first with one FAL attempt, streamed OpenAI
submissions, absorbed unknown attempts, a route circuit breaker, gateway
hardening, and parallel page lanes (see
[stage contracts](../reference/stage-contracts.md)). The general route/attempt
records, durable FAL receipts, and text fallback below remain design.

## Recommendation

Keep stage model choices stable. Give each logical model an ordered set of
explicit provider routes, and let one application-owned execution module choose
an eligible route for each request. Compile a separate route-specific payload for
each candidate route from the same frozen semantic inputs, and freeze it before
spend; an attempt never recompiles from live settings. A fallback must preserve
the requested generation contract; it must
never quietly change models, remove references, weaken structured output, or
alter lettering mode.

Allow at most one primary and one backup per model, and add a backup only where
this document approves one. No racing providers, recursive fallback chains,
or quality-based rerouting. Automatic image resubmission after an uncertain
outcome is forbidden except for the one approved OpenAI-to-FAL attempt below.
Availability fallback and creative repair are separate.

## Decisions (2026-09-28)

- **Text: no backups for now.** Claude models stay on the Anthropic API directly:
  Fable 5.1, Opus 5.5, and the newly added Sonnet 5.5 (`claude-sonnet-5-5`).
  Opus 5.5 cloud-platform backups (Vertex AI, Bedrock) are on hold. The text
  sections below still apply to routes and attempts. Text fallback activation
  (rollout step 3) waits for a new decision.
- **Text effort is low.** Reasoning text routes run at low effort. GPT-6 routes
  set `reasoning_effort: low` on the gateway, and Claude routes send
  `output_config.effort: low`. Routes that already disable reasoning (MiMo,
  DeepSeek) stay disabled. A backup route must run at the same effort.
- **Images: OpenAI primary, FAL backup, for all Sunburst images
  (2026-09-29, implemented).** `image-sunburst` means OpenAI first, then one FAL
  attempt, for new Draw editions and for every new Style/Cast image (samples,
  references, covers). There is no operator priority selector: the order is
  fixed in code. Existing FAL-bound editions and already-frozen FAL requests stay
  on FAL (see [Identities and ownership](#identities-and-ownership)).
  [OpenAI primary consequences](#openai-primary-consequences) lists what that
  order changes.
- **Unknown OpenAI outcomes get one FAL attempt, and Canary absorbs the cost
  (implemented: `run_openai_first` in `image_route_fallback.py`, used by
  `SunburstFallbackPageAdapter` for Draw and `generate_wire_image` for
  Style/Cast).**
  OpenAI's Images API gives no way to recover a result. When an OpenAI Sunburst
  submission ends `unknown`, the coordinator may make exactly one FAL attempt
  for the same frozen request. A lost OpenAI result can never arrive later, so
  this cannot publish a duplicate page; the only risk is paying twice. The lost
  attempt stays in the usage record with its own cost, but it is not charged to
  the user. AGENTS.md records this as the single exception to the
  no-resubmission guardrail.
- **Stream OpenAI image requests (implemented).** LiteLLM 1.101 cannot stream
  images, so the custom gateway handler `litellm_handlers/openai_image_stream.py`
  calls OpenAI with `stream=true` and `partial_images=0`. Each failure carries
  its phase (`submit_connect`, `submit`, `submit_transport`, `stream`,
  `result`). The live check on 2026-09-28 showed OpenAI opens the stream only
  when the image is ready (about 17 seconds, under a second before
  `completed`), so the stream opening is not early proof of acceptance: a lost
  connection is almost always `submit_transport`. Both count as unknown and get
  the one absorbed FAL attempt. Streaming identifies failures; it does not
  recover them. The Style/Cast sizes were certified live on 2026-09-29
  (`--asset-sizes`): 1024x1280 with one reference, 768x1024, and 1344x768 all
  returned their exact size in 15–22 seconds, with output tokens (378, 301, 255)
  equal to the `expected_*` settlement estimates. The Responses API's
  background mode was rejected: its chat model revises the image prompt, which
  breaks verbatim visual anchors.
- **Parallel page lanes cover OpenAI (implemented).** `is_parallel_page_draw`
  admits complete-page Draw jobs whose frozen provider is in
  `PARALLEL_PAGE_PROVIDERS` (`fal-queue`, `openai`), with three pages per
  account. OpenAI 429s are retried before anything is generated.
- **Gateway hardening (implemented).** The gateway runs on LiteLLM's bundled
  model map (`LITELLM_LOCAL_MODEL_COST_MAP=True`) with `drop_params: false`.
  Every route declares its capabilities and prices in `model_info`. Before this,
  a failed map download at boot made GPT-6, MiMo, and DeepSeek report a cost of
  0.0, which the app would settle as free, and made MiMo's `reasoning_effort`
  unsupported. Contract tests check each route's upstream controls and require
  its gateway-reported cost to equal the app's pricing override.

## Evidence in the current implementation

- `text_models.py` combines logical identity and route-specific wire behavior.
  `ai/client.py` builds Claude `output_config`, effort, thinking headroom, token
  limits, and streaming fields from it. Those fields cannot be forwarded blindly
  to a different provider. The rest of each route's wire lives in the gateway
  deployment's `litellm_params` (Opus `thinking.display: summarized`, which the
  first-content watchdog depends on; OpenAI `reasoning_effort`; Together and
  OpenRouter `extra_body`). The app cannot see those fields today, so an
  app-side execution fingerprint does not describe the full upstream request.
- `litellm/config.yaml` exposes one deployment per selectable alias and
  disables gateway retries. Since 2026-09-28 it also disables `drop_params` and
  pins each route's capabilities and prices. Turning off `drop_params` is not
  sufficient on its own. The pinned LiteLLM 1.101 still drops some parameters
  regardless: `reasoning_effort` when a Claude request carries `output_config`,
  and standard image arguments such as `quality` for custom providers (see the
  comments in `text_models.py` and `fal_provider.py`). Certify the final
  upstream payload, not just app output. LiteLLM 1.103.0 behaves the same.
- `compiled_request.py` calls its request provider-independent but includes
  provider key/model in its hash. `provider_wire.py` additionally freezes the
  exact provider request and execution fingerprint. Separating these identities
  requires an explicit schema change, not changing a hash comparison exception.
  Compilation also depends on the route: the reference plan applies the route
  profile's hard cap before compilation. `ImageRoute` is a model-family enum,
  not a provider route: `GPT_IMAGE_2` covers GPT Image 2, Sunburst, and Flare.
  `image_model_profile()` gave one logical model different contracts on
  different deployments: `image-sunburst` (FAL) resolved to 4 references, and
  `openai/gpt-image-2.5-sunburst` to 16. Resolved 2026-09-29: `image-sunburst`
  now describes the OpenAI-first pair and resolves to 16 for Style/Cast too,
  matching Draw, which already sends up to 16 references to both routes.
  Retained FAL literals keep 4.
- `ai/providers/litellm_http.py` already has distinct provider serializers and
  conservative image submission handling (`retry_ambiguous=False`). Reuse these
  implementations.
- Text calls follow a different policy today. `ai/client.py` retries a 429 up to
  5 times, and retries 502/503/504 and transport errors up to 3 times, even after
  dispatch. It retries a read timeout once and redraws malformed JSON up to 2
  more times. Each of these may re-bill. The fallback design has to state
  whether it keeps, bounds, or removes each of these budgets. Folding them
  silently into a smaller total would lower text reliability.
- `litellm_handlers/fal_provider.py` submits, polls, downloads, and obtains cost
  within one gateway request. The request ID appears in gateway logs, in the
  success response, and in the text of `FalQueueError`. However, the proxy wraps
  custom-provider exceptions in a generic HTTP 500, so `litellm_http.py`
  regex-parses the phase and request ID out of the message. A submit-phase
  capacity rejection therefore reaches the app looking like an ambiguous 5xx.
  Recovery also needs a durable acceptance receipt that is written before
  polling finishes, and structured phase evidence rather than message parsing.
- The durable queue freezes page inputs and marks interrupted execution unknown.
  Admission chooses the lane from the frozen `request.provider`
  (`is_parallel_page_draw`). It does this at dispatch, through the Procrastinate
  lock and the parallel account gate, before any attempt runs. FAL and OpenAI
  pages both get parallel lanes, so a fallback between them keeps the right lane
  class, but a lane still cannot describe which route an attempt used.

Relevant contracts: [job queue](../reference/job-queue.md),
[stage contracts](../reference/stage-contracts.md),
[model settings](../reference/account-model-settings.md),
[reference authority](../adr/0012-page-level-reference-consistency.md), and
[immutable lettering choice](../adr/0022-project-lettering-choice.md).

## Identities and ownership

| Record | Owns | Example |
| --- | --- | --- |
| Logical model | Selected model identity and required behavior | `image-sunburst`, `claude-sonnet-5-5` |
| Provider route | Deployment, upstream model ID, adapter revision, gateway-injected params, capabilities, limits, credentials reference, pricing key, operational enablement | `sunburst-openai`, `sunburst-fal` |
| Generation contract | Immutable model/profile requirements and semantic input | Schema, reasoning intent, reference bytes/order/roles, dimensions, lettering mode |
| Execution plan | Versioned ordered eligible routes, policy, deadline and spend allowance | Primary then one certified backup |
| Attempt | Exact frozen wire, route/version, receipt, result, usage and failure evidence | A single potentially paid submission |

Stage settings continue to select logical models. Operator configuration owns
routes and their order. Provider capabilities describe model + endpoint + adapter
version, not an entire provider. Exact model versions should be pinned where
available; an unversioned slug needs explicit documented equivalence evidence
and recertification on known upstream changes. A shared marketing name alone
does not prove equivalent serving behavior.

The existing `ImageRoute` enum names model families and conflicts with "provider
route" as used here. Rename it, for example to `ImageModelFamily`, before adding
route records. The logical model's contract, not the deployment, owns reference
caps, roles, prompt budget, and controls. Derive each route's capability from a
single table, the same one the compiler reads, so eligibility and compilation
cannot disagree.

For new Draw profiles, freeze logical model identity, semantic requirements, and
certified route revisions in the edition profile. Freeze route order and policy
for an operation at admission. Live operator disablement can remove a route from
consideration, but must not silently add one to an admitted operation. New route
certification does not retroactively rebind editions.

Existing provider-bound editions and queued wires stay on their original route.
They do not acquire backups automatically. Introduce a new explicit schema/profile
for fallback-capable editions; incompatible generation artifacts require the
normal rerun/new-edition path. Preserve existing output for supported read/review.

## Small caller interface, provider-specific adapters

Callers submit a text or image request through the existing AI interface. The
execution module privately performs eligibility, compilation, attempt journaling,
admission, dispatch, normalization, and failure decisions. Stage code contains no
provider fallback branches and keeps using `StageRuntime` for lifecycle events.

Adapters implement these internal responsibilities:

1. Validate that the route can express all required request semantics.
2. Compile a frozen route-specific payload without modifying semantic inputs.
3. Submit once and expose acceptance evidence when the provider supports it.
4. Retrieve an existing result when a durable receipt allows retrieval.
5. Normalize output, usage, refusal, and phase-aware failure evidence.

Adapters reject a reference they cannot encode instead of filtering it out.
The FAL handler currently drops any image whose bytes read as `None`. The route
revision covers the gateway deployment's injected `litellm_params`, so the
attempt fingerprint describes what actually reaches upstream.

Keep LiteLLM as transport for supported routes, with explicit deployment aliases
and no hidden fallback. For example, the app resolves `image-sunburst` into
`image-sunburst-openai` (primary) or the FAL deployment (backup) before
serialization. The FAL deployment keeps the gateway name `image-sunburst`, so
retained FAL editions and frozen FAL requests keep resolving to it. Aggregator routes such as OpenRouter are hidden routers unless
the deployment pins a single upstream provider, disables provider fallbacks,
and requires parameters. Model aliases and price configuration remain
configuration-owned.

The application owns fallback because it knows frozen artifact contracts, credits,
and durable operation state. A gateway-only router does not have this evidence.
For FAL recovery, expose submit/status/result through a thin gateway extension
backed by a durable attempt receipt store; reuse the existing handler's payload
and result code. Do not introduce a second independent fallback engine there.
If that extension is deferred, uncertain calls remain blocked; logs alone never
authorize resubmission.

## Compatibility is evaluated for this request

Text eligibility covers schema dialect and enforcement, vision attachments,
context/output limits, reasoning effort semantics and budget, system messages,
streaming/error events, and relevant cache behavior. Cache hits are not assumed
portable: preserve content, estimate cold input cost on the backup, and account
for its actual cache usage. Route-specific schema normalization must preserve
the application's validation contract. Always validate the returned object.

Image eligibility covers generation/edit operation, exact dimensions, quality
semantics, all selected reference bytes/order/roles, parent-image semantics,
prompt size, and output/lettering requirements. Identical parameter names do not
establish identical semantics. Never silently clamp quality or dimensions, trim
protected prose, or drop/repack authorities to qualify for backup.

Reference selection belongs to the semantic contract. Select references once,
against the logical model's cap. A route qualifies only if it accepts that
exact set. Today FAL Sunburst selects at most 4 references and OpenAI Sunburst
at most 16. Decide which cap is correct before any parity work. If each route
kept its own cap, the same page could carry different authorities depending on
the route.

Both current image serializers silently remap sizes they cannot express.
`litellm_http._image_size` falls back to 1024x1024, 1024x1536, or 1536x1024 for
OpenAI. `fal_provider._image_size` falls back to named presets or `auto_2K`.
An adapter must reject an unsupported size during preflight instead.

Preflight each candidate and freeze eligible wires before spending. If the primary
can handle a request but the backup cannot, run primary-only and retain the backup
ineligibility reason. Do not shrink primary capabilities to their intersection.
If no route qualifies, reject before spend with an actionable reason.

Maintain separate semantic-input and attempt-wire hashes. The first binds model
contract, prompt, schema/copy, dimensions, controls, and content-addressed inputs;
the second also binds provider, upstream model, adapter revision and serialized
representation. A hash is never a provider idempotency guarantee. Attempt IDs are
unique; operation IDs connect them. Publication still checks the original parent
revision and artifact prerequisites.

## OpenAI primary consequences

Putting OpenAI ahead of FAL changes more than route order:

- **No recovery on the primary.** OpenAI image generation is one synchronous
  request with no durable receipt or retrieval. Explicit rejections arrive
  before any image work, but a request that loses its connection is lost
  whether or not generation had started. Under the approved exception, an `unknown` OpenAI Sunburst outcome gets
  one FAL attempt at Canary's cost. Explicit 429s and capacity rejections,
  credential failures, and failures before dispatch fall back as for any route.
  An unknown FAL backup attempt is retained for reconciliation exactly as a
  FAL-primary attempt is today; durable FAL receipts would improve both and
  remain a follow-up.
- **Throughput.** Parallel page lanes now cover OpenAI pages. OpenAI image rate
  limits are org-wide, so the global `CANARY_GENERATION_WORKERS` bound matters
  more than the per-account three. Size it from the production account's image
  rate limit once that is known.
- **Reference parity.** Draw uses page profiles, which allow 16 references on
  both routes (FAL documents a 16-image limit). The 4-vs-16 mismatch in
  `image_model_profile()` affects Style/Cast images only.
- **Dimensions and quality.** Both routes must accept the new profile's exact
  page and proof dimensions, without the silent remapping described above. They
  must also mean the same thing by `quality`. Confirm OpenAI's limits for
  Sunburst sizes rather than inferring them from GPT Image 2's
  `_valid_gpt_image_2_size`.
- **Cost settlement.** OpenAI reports token usage in the response. FAL
  settles from its billing-events lookup, or from a labelled estimate when no
  admin key is set. Each attempt settles on its own route's evidence. Both
  pricing keys must exist before the profile can be admitted.
- **Account access.** OpenAI Sunburst access, organization verification, and
  image rate limits on the production account are unverified. Certify them
  before any profile names OpenAI as primary.

## Failure decisions

Normalize two independent facts: execution certainty (`not_submitted`,
`accepted`, `completed`, `unknown`) and failure kind. Also retain billing certainty,
request ID, phase and redacted diagnostics. HTTP status alone is insufficient.
Phase evidence has to survive the gateway as a structured field. Today a FAL
submit rejection and a post-acceptance poll failure both arrive as HTTP 500,
and only message parsing tells them apart. Also check how the pinned gateway
reports Anthropic `overloaded_error` (529) and OpenAI overload responses. That
is the most common real outage signal. It counts as an explicit capacity
rejection only when it arrives before any stream content with its upstream
type intact; the current `_RETRYABLE_STATUS_CODES` does not include 529. An
error event after a streamed HTTP 200 is post-acceptance.

| Evidence | Default behavior |
| --- | --- |
| Route disabled or circuit open before submission | Choose next eligible route |
| Proven connection failure before dispatch, or explicit capacity rejection before acceptance | Bounded backoff or eligible backup, within one shared attempt/deadline budget |
| Provider credential/access failure before acceptance | Disable affected route, alert operator, use eligible backup; app authentication failures still stop |
| Invalid request, unsupported required parameter, schema/compiler defect | Stop with actionable diagnostic; do not hide the defect by rerouting |
| Refusal or content-policy rejection | Stop; use the existing explicit correction workflow if appropriate |
| Accepted FAL work, polling timeout, download failure | Recover status/result using the same receipt; never submit elsewhere |
| Timeout/disconnect after dispatch, generic gateway 5xx, missing acceptance evidence | Outcome unknown; no automatic fallback, except one FAL attempt after an unknown OpenAI Sunburst submission (cost absorbed) |
| Definitive terminal provider failure after acceptance | Retain cost/evidence and fail; explicit retry in the initial release |
| Completed output fails JSON, geometry, or visual validation | Preserve result and usage; route through validation/correction, not provider fallback |
| Cancellation or exhausted credit/deadline budget | Stop; cancellation does not establish provider non-execution |

The initial *cross-route* rule is deliberately the same conservative rule for
text and images: switch routes only after proven pre-acceptance failures. Same-route
retries are a separate question, and the two media already differ. Images never
retry an ambiguous submission. Text currently retries ambiguous 502/503/504
responses, transport errors, and a read timeout on the same route, accepting
duplicate spend. Keep those text budgets as an explicit, documented
duplicate-spend policy, and move them under the coordinator so that each retry
is a journaled attempt with its own usage event. Do not remove them silently to
fit a smaller total. If a budget is reduced, record that as a reliability
decision. Never concatenate partial streams from different providers. JSON
redraws (`_JSON_PARSE_MAX_RETRIES`) and schema repair are new logical requests,
subject to existing narrative call limits, not availability fallback.

Use one coordinator for retries and fallback. At most one route switch per logical
request (primary, then one backup), each route with its own bounded same-route
budget, all within one total deadline. A route-local 429/overload budget that
would outlast the deadline should yield to an eligible backup instead of sleeping
through it. Respect route-local Retry-After/cooldowns. Read-only polling/download
retries have their own bounded budget and cannot become submissions. Audit
SDK/gateway retry defaults too, including FAL's provider-side re-queueing (the
`X-Fal-No-Retry` header disables it).

## Durability, admission, and money

Journal an attempt and reserve its spend capacity before dispatch. Record the
receipt immediately on acceptance. A crash in the submit/receipt gap remains
unknown unless the provider can authoritatively reconcile it; there is no
cross-provider exactly-once guarantee. Persist successful raw response evidence
before application validation/publication so local failures can resume without
another generation. Claim attempts atomically and allow only one live submission
per logical request. Late responses remain evidence and cannot overwrite a
terminal operation or newer artifact revision.

Acquire concurrency/rate limits for the actual selected route. A FAL-origin page
must not bypass OpenAI admission limits when it falls back. Lanes are chosen
at dispatch, before any attempt exists, so a lane cannot describe the actual
route. Key lane choice on the admitted execution plan instead of
`request.provider`: a plan gets the parallel page lane only if every route in
it permits parallel pages. Each attempt also takes a route permit inside the
execution module before it submits. Retain the current
artifact/account ownership rules; route permits are additional execution gates.
Circuit breakers are scoped to route and credential/account quota where relevant,
use shared operational state, and must not treat content refusals as outages.
Half-open probes use normal authorized traffic, not background paid generations.

Every attempt gets its own usage event linked to the logical call and job. Record
requested model, attempted route, actual provider model, adapter version, fallback
reason, execution certainty, provider usage/cost source, and credit settlement.
Unknown cost remains unknown. Failed/abandoned attempt charges cannot disappear
when a later attempt succeeds. Existing settlement/reconciliation remains the
single authority; no second credit ledger.

Canary absorbs the cost of an unknown OpenAI attempt that is followed by the
approved FAL attempt. The OpenAI attempt keeps its failed usage event; the page
provenance records that event ID and its estimated cost as absorbed. The user's
credits settle only the attempt that produced the page, so the page's single
reservation is enough: both routes share the same pricing. Style/Cast images
authorize a per-call guarantee instead; the OpenAI attempt's guarantee is
released before the FAL attempt authorizes its own, so one image never holds
two. Fallbacks, absorbed attempts, and circuit openings are counted in
`canary_image_route_fallbacks_total`, `canary_absorbed_image_attempts_total`
(both labelled `surface` = `draw` or `asset`), and
`canary_image_route_circuit_opened_total`.

For the initial safe-fallback policy, estimate enough for the most expensive
eligible route, including cold caches. Recheck/authorize the actual attempt before
submission; release the prior reservation only when existing settlement evidence
allows it. A provider change must not exceed the authorized operation allowance.
If capacity is insufficient, fail before backup spend. Show estimates as
`~N credits`; keep estimates, provider cost, and charged credits distinct.

## Certification and rollout

1. Separate logical models from explicit provider routes, keeping each current
   route as its sole default. Introduce attempts and error certainty without
   activating fallback. Add configuration checks for missing routes/prices and
   incompatible profiles. Preserve local subscription/mock funding isolation.
2. Move wire differences behind adapters and test actual upstream serialization
   through the pinned gateway. *Done 2026-09-28:* `drop_params` is off, the
   gateway runs on the bundled map, and contract tests capture each text route's
   upstream request and reported cost. Still to do: capture image routes the
   same way, and catch drops that happen regardless of `drop_params`. Make gateway error phase and upstream error type
   structured, not message text. Test the Anthropic and cloud-platform Claude
   routes independently. Structured output (`output_config.format`), effort,
   adaptive thinking display, and streamed reasoning deltas must be verified per
   platform at the wire.
3. *On hold (2026-09-28).* Text fallback would activate here for proven
   pre-acceptance failures, including classified overload rejections, once a
   candidate deployment's structured output, effort, streaming, limits, and
   usage are verified. No rollout depends on a guessed platform model ID.
4. Resolve the Sunburst reference-cap discrepancy and rename `ImageRoute`.
   Certify OpenAI Sunburst access, limits, sizes, and streaming through the
   gateway. Then add an OpenAI image route permit, durable FAL
   receipt/retrieval support, the new image profile/schema with
   `sunburst-openai` as primary and `sunburst-fal` as backup, streaming OpenAI
   submissions, absorbed-cost settlement, and image adapter parity checks. Only
   after that, enable image fallback, including the one approved attempt after
   an unknown outcome, and only for eligible new-profile requests. (Parallel
   lanes for OpenAI pages landed on 2026-09-28.)
5. Add route health visibility and operator disablement. Report fallback rate,
   incompatibility reasons, unknown outcomes, and per-route latency/cost.

Provider-free contract tests cover eligibility and no silent degradation; exact
text/image serialization including gateway-injected params; 429 and classified
overload versus ambiguous 5xx; gateway-wrapped FAL phases; failure at submit, acceptance,
poll, download and publication; restart gaps and duplicate dispatch; stream errors
and partial text; refusal; reference overflow; shared retry limits; per-route
admission; accounting/unknown cost; and immutable old editions. Keep fixture
coverage tied to adapter/gateway versions. Small separately authorized live checks
establish access and wire support; visual review is needed to assess image parity.
Mocked tests cannot certify image quality.

## External evidence and remaining verification

Checked September 28, 2026:

- Anthropic's [Opus 5.5 migration guide](https://platform.claude.com/docs/en/models/opus-5-5/migration-guide)
  documents effort in `output_config`, always-on adaptive thinking, and the move
  to `output_config.format`. It says to use each platform's own model ID on
  Amazon Bedrock, Claude Platform on AWS, Google Cloud, and Microsoft Foundry.
  Together AI is not a listed Claude platform, and OpenRouter's
  [Opus 5.5 listing](https://openrouter.ai/anthropic/claude-opus-5.5) names
  only Anthropic, Bedrock, Azure, Vertex, and Claude Platform on AWS as
  providers. Drop the Together candidate. If Opus backups resume, Google Cloud
  Vertex AI is the natural first candidate, since the gateway already holds
  Vertex credentials for image routes; Bedrock is the alternative. Neither
  platform's structured-output, effort, or streaming parity was verified in
  this pass.
- Anthropic's [Sonnet 5.5 page](https://platform.claude.com/docs/en/models/sonnet-5-5/overview)
  (released September 28, 2026) lists `claude-sonnet-5-5` at $2 input and $10
  output per million tokens, a 128K output limit, adaptive thinking on by
  default, a default effort of `high`, and a 400 for non-default sampling
  parameters. The pinned LiteLLM's bundled model map does not include it, and
  neither did the remote map on this date. With `drop_params` on, LiteLLM
  stripped `output_config.effort` from models whose map entry lacks
  `supports_output_config`; Opus 5.5 had been relying on the map downloaded at
  boot to keep it. Both routes now declare their capabilities and prices in
  `model_info`, and `drop_params` is off.
- FAL lists separate Sunburst generation/edit routes on its
  [GPT Image 2.5 page](https://fal.ai/gpt-image-2.5).
  OpenAI lists Sunburst on its [pricing page](https://platform.openai.com/pricing).
  Listings establish availability claims, not endpoint parity or account access.
- FAL's [queue documentation](https://fal.ai/docs/documentation/model-apis/inference/queue)
  exposes request IDs and separate status/result retrieval. It also describes
  provider-managed retries: a request whose runner fails with 503, 504, or a
  connection error is re-queued up to 10 times unless it is submitted with
  `X-Fal-No-Retry`. That reinforces why an accepted request cannot be treated
  as safe to replace merely because the caller times out.

OpenAI Sunburst limits, equivalent quality settings, and both accounts' real access
still need route certification. Both alternatives may share upstream model
infrastructure with their primary, so this improves delivery-path resilience
without guaranteeing independence from a model-wide outage.

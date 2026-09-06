# LiteLLM dependency and development observability review

Date: 2026-09-05. Scope: repository source and public primary documentation. The recommendation and alternatives are the historical review; implementation status is tracked separately below. No services, model calls, benchmarks, installs, or production changes were performed.

## Recommendation

**Decouple observability from LiteLLM; retain the existing proxy for live generation rather than replace it solely to improve debugging.**

The hard dependency is real for the inspected live text, Style/Cast image, and complete-page Draw paths. It is a **transport and provider-compatibility dependency**, not a requirement for useful observability. Canary already owns generation events, Langfuse ingestion, retry policy, validation, billing settlement, and recovery state. LiteLLM's built-in Langfuse callback is explicitly disabled in favor of application-owned reporting. [R1–R6, R11–R13, R17, R21]

For the stated development goal, choose **application-owned diagnostics with a local console/artifact baseline (Alternative A), and optional OpenTelemetry export to a single general-purpose viewer such as Logfire (Alternative B)**. Do not make a dashboard a prerequisite for reproducing a failure. The recommendation is about ownership and coverage first, vendor second; it does not require adopting Pydantic AI or another model gateway.

[INFERENCE] The most valuable improvement is connecting a failed job to its model attempt, validation result, saved artifact, and safe recovery action—not replacing the proxy with another proxy. A direct-provider architecture could simplify the live request path, but this source review does not establish that rewriting the existing integrations would repay its cost faster than improving application-level evidence.

## Current responsibilities and dependency boundaries

| Responsibility | Current owner and evidence | Implication |
| --- | --- | --- |
| Live text routing | `ai/client.py` posts OpenAI-shaped chat requests to `litellm_base_url`; gateway aliases select Vertex or Anthropic models. [R1, R3] | Removing LiteLLM is not an observability-only change. |
| Style/Cast image routing | The selector returns `LitellmHttpProvider`; the wire-image entry point explicitly rejects other adapter types. It posts multipart edits or JSON generations to the gateway. [R2] | An interface exists, but there is not an interchangeable second live adapter in this path. |
| Complete-page Draw | Despite its native-sounding name, `GoogleVertexCompletePageTransport` posts to the same gateway with a frozen complete-page manifest. [R4] | It is not already a direct Vertex bypass. |
| Provider-specific image behavior | Custom Vertex code verifies manifests/reference images, builds native GenAI requests, maps errors, checks geometry, and packages usage/images. fal code submits, polls, fetches, and downloads queued output. Reve code translates the wire manifest to its v2 endpoint. [R7–R9] | These are substantive integrations, not functions a telemetry product replaces. |
| Dependency isolation | The application manifest does not declare the LiteLLM SDK; the gateway image pins LiteLLM and separately installs `google-genai==1.75.0`. [R10] | “Remove the Python package” misidentifies the current dependency. The operational coupling is a separate gateway process and its protocol/configuration. |
| Retries and output repair | Gateway `num_retries` is zero. Canary handles transient/rate-limit retries, JSON parsing retries, and schema validation/local repair. Complete-page submission disables ambiguous automatic retries. [R3, R4, R11, R12] | Keep recovery semantics in Canary rather than duplicating them in an observability tool. |
| Usage and billing | Canary reads response costs, resolves a cached cost map, persists `ai_usage_events`, and debits its own ledger. [R5, R13] | The LiteLLM pricing dataset can be considered separately from running its proxy. Application usage persistence is not disposable telemetry. |
| LLM observations | Canary emits Langfuse trace/generation REST batches itself when credentials and host are present. [R6] | Langfuse and LiteLLM are already logically separable. |

### What the local launcher actually requires

The default `scripts/dev.sh` live mode requires Docker, LiteLLM, and LiteLLM's Postgres service. **Langfuse is opt-in through `--observability`, not part of the launcher's default dependency set.** That option names six additional services: web, worker, Postgres, ClickHouse, Redis, and MinIO. This is a source-derived count, not a measurement of running containers. [R14, R15]

The `--mock` branch instead launches a local replay service from a completed-project fixture and skips the live gateway/Docker checks. That supports gateway-free application iteration at the launcher level; it does not prove the fixture exists, current replay compatibility, or reproduction of real provider faults. [R14]

The configured local proxy depends on its own database. Do not generalize that to “every use of LiteLLM requires Postgres”: upstream distinguishes the Python SDK from the proxy and documents Postgres for virtual-key management. Nor should that documentation be treated as proof that deleting the database from Canary's pinned configuration would work. [R15, D1, D2]

## Where the development loop currently loses information

### 1. Successful generation is not successful work

The chat client finalizes a generation as `succeeded` before its caller parses the JSON. Additional typed validation and local repair happen farther up the stack. Thus a successful Langfuse generation can coexist with a failed application operation; that is a difference in event meaning, not evidence that the provider succeeded at Canary's entire task. [R12, R16]

Complete-page generation similarly finalizes its model event before the caller writes the render/provenance and runs OCR analysis. A trace centered only on the model cannot explain the whole failure/recovery sequence. [R4, R17]

**Recommendation:** distinguish transport outcome, usable-output validation, persistence, and workflow outcome in developer evidence. Preserve successful paid model usage even when a later phase fails.

### 2. Waiting and retries are not a complete attempt timeline

The text path logs an `AI request issued` breadcrumb before submission precisely because its Langfuse observation is sent only on finalization. Stream progress and retry warnings exist, but the transport retry loop has no separate persisted attempt event in the inspected path; it lives inside the one logical call. [R6, R11, R16]

[INFERENCE] A developer can otherwise mistake “waiting for first content,” “backing off after a 429,” and “hung after useful output” for the same delay. A viewer does not resolve this unless Canary emits those distinctions. Standard OTel provides spans, events, links, and exception records, but they must be instrumented. [D3]

### 3. OTel export exists; comprehensive app tracing does not follow from enabling it

`configure_telemetry()` is opt-in and configures a batched HTTP OTLP **trace** exporter. It does not itself instrument the application or export the existing Python logs. The older API logging helper explicitly skips provider spans for LiteLLM and several major LLM providers. The request middleware records metrics and terminal messages, not an OTel request span. [R18, R19]

Therefore **changing an OTLP endpoint, or setting `CANARY_OTEL_ENABLED=1`, is not a complete observability replacement**. Neither Alternative A nor B is presented as already implemented end-to-end.

### 4. Useful local evidence exists, but it is fragmented

The configured server logger is Rich on stderr, not a persistent JSONL run journal; timestamps are off by default. Unhandled HTTP errors include a request ID, and the response gets `X-Request-ID`, but the ordinary request log line omits that ID. The AI metadata separately carries request/project/stage/event identifiers. Background generation jobs classify failures, while full exception logging is opt-in via `CANARY_LOG_JOB_TRACEBACKS`. [R18–R20]

The application also stores stage errors, exposes failed-stage/reset endpoints, and saves complete-page request/render/provenance artifacts. It explicitly distinguishes a rendered page with failed analysis from a page needing another generation. These are better recovery evidence than a model dashboard alone. They are not a universal replay engine. [R17, R21]

**Recommendation:** the developer-facing evidence should join these existing identities and artifacts rather than add a competing state store. Request IDs and Langfuse trace labels must not be assumed to be an already propagated OTel trace context.

### 5. Optional observability is not automatically costless or reliable

Source-visible concerns in the current call path:

- `ai_usage_events` insert/update use the synchronous Supabase client from async generation code. The DB client has a 120-second timeout. Exceptions are caught, but the call still waits while the synchronous operation runs. **[INFERENCE]** This can obstruct the event loop when the database is slow; its impact here has not been measured. [R5, R22]
- Langfuse submission is scheduled as an asyncio task but shares the model HTTP client. That pool has 100 maximum connections and long model-request timeouts. **[INFERENCE]** Slow ingestion can contend with model traffic. [R6, R23]
- `_post_langfuse_batch` catches transport exceptions but does not check the HTTP status or ingestion response body. A rejected batch therefore need not produce its `Langfuse ingestion failed` warning. There is no task tracking/drain in the inspected emission function. **[INFERENCE]** Some final observations can be lost during shutdown. [R6]
- Prompt truncation is not privacy redaction. The chat path explicitly builds prompt-content payloads for Langfuse; that path is separate from the older logging helper's prompt opt-in. [R16, R19]

These are static findings, not reproduced incidents. In particular, do **not** fix observability overhead by removing `ai_usage_events`: successful persistence currently gates per-call billing settlement. A sampled or best-effort trace cannot replace that ledger contract. [R5, R13]

## Two simpler observability alternatives

Both alternatives leave model routing unchanged. Their potential gains come from application coverage and fewer required observability services, not an asserted improvement in provider inference speed.

### Alternative A — local application diagnostics, optional OTel console

Use the existing Rich terminal output and saved failure/provenance artifacts as the development baseline. Where causal tracing is needed, standard OTel spans/events can be exported locally through `ConsoleSpanExporter`, which ships with `opentelemetry-sdk`; no telemetry backend is needed for console export. Canary already declares optional OTel dependencies, but its current bootstrap only selects OTLP, so this console choice is a recommendation, not an existing switch. [R10, R17–R19, R21, D3, D4]

- **Error discovery:** job/phase failures and tracebacks remain visible without a dashboard or ingest credential.
- **Debugging:** the useful unit is a job/run plus its model attempts, validation outcomes, and artifact identities. **[INFERENCE]** Keeping that evidence local reduces cross-tool searching for isolated failures.
- **Recovery:** existing failed-stage and page-analysis semantics remain authoritative. A console exporter does not perform retries or reconstruct lost state.
- **Simplicity/efficiency:** zero additional observability services; still the current live model gateway and application database dependencies. No telemetry upload is necessary for the local console/artifact view. This does not make model calls offline or disable other already-configured exporters.
- **Limitations:** terminal history is weak for concurrent jobs, historical queries, and sharing. Saved artifacts are not comprehensive structured logs. Do not grow a home-built dashboard/database simply to avoid choosing a viewer.

**Best fit:** everyday local debugging, offline inspection of already-saved evidence, and development where exporting novel text or images is unacceptable.

### Alternative B — application OTel plus optional hosted Logfire

Logfire accepts standard OTel export, including a documented Python `OTLPSpanExporter` path; its SDK is optional for basic ingestion. Its Live view supports trace inspection, SQL filtering, attributes, and exception details. This is a telemetry destination, not a required model gateway. [D5, D6]

- **Error discovery:** one searchable application-level view can include model failures and downstream validation/persistence failures, **provided Canary emits them**.
- **Debugging:** use the application job as the causal unit. HTTPX instrumentation can expose outbound HTTP calls, status, duration, and transport errors, but does not infer domain validation, page provenance, or a custom gateway handler's internal work. [D7]
- **Recovery:** a trace can explain what to retry; Canary still decides and executes the recovery. Exceptions swallowed by worker/repair code require explicit recording, rather than relying on an outer context manager to notice them. [R12, R20, D8]
- **Simplicity/efficiency:** **[INFERENCE]** a managed viewer removes the six local Langfuse services from this observability option. It adds an account, authentication, network/export work, and service/usage dependence; it is not “zero overhead.” Retain local diagnostic output when export is unavailable.
- **Limitations/privacy:** do not blindly export the existing prompt payloads or turn on HTTP body/header capture. HTTPX body/header capture is off by default, and Logfire explicitly warns that LLM message attributes bypass its normal scrubbing. Raw OTLP ingestion does not imply that Logfire SDK scrubbing ran. External disclosure would require a separate decision; nothing was connected or uploaded in this review. [D5, D7, D9]

**Best fit:** concurrent/background failures where searchable causal history is worth an optional hosted tool. Prefer it as an app debugger rather than adopting another AI framework for its tracing integration.

### Comparison with the current setup

| Question | Current optional Langfuse path | Alternative A | Alternative B |
| --- | --- | --- | --- |
| Required local observability services | None by default; six when explicitly requested. [R14] | None. | None for the hosted viewer; an external service replaces local hosting. |
| What explains a failure? | App-emitted completed model observations plus separate console/state/artifact evidence. [R6, R17–R21] | Local job/phase evidence and artifacts; scoped console traces if added. | Searchable app traces including the same evidence, if instrumented. |
| In-flight visibility | Text breadcrumbs/progress outside the finalized Langfuse observation. [R16] | Start/progress events must remain visible; end-only spans alone do not solve waiting. | Same requirement; generic HTTPX docs say spans appear after completion. [D7] |
| What performs recovery? | Canary. | Canary. | Canary. |
| Main tradeoff | Existing integration and model-oriented view, but incomplete workflow coverage and substantial optional hosting. | Fewest moving parts; weaker history/search. | Better search/navigation capabilities; export/privacy/vendor costs and instrumentation work. |

The existing direct Langfuse integration is also a legitimate retention choice if its model-oriented view is useful. Its shortcomings here are not proof that Langfuse itself cannot support richer tracing. Merely switching viewers without changing the evidence emitted would preserve the important blind spots.

## Is removing the gateway itself warranted?

Separate this decision from observability:

| Transport choice | Assessment for Canary |
| --- | --- |
| Retain the existing proxy | **Recommended for the current live paths.** Preserves the alias catalog, custom wire protocols, image semantics, and isolated SDK environment. The benefit is existing compatibility, not superior debugging. [R1–R4, R7–R10] |
| Use the LiteLLM SDK in-process | Upstream supports an in-process SDK with normalized responses and provider exceptions. **[INFERENCE]** This can remove the proxy HTTP hop/process but keeps LiteLLM as an application dependency, moves dependency/credential concerns into Canary, and does not automatically preserve the custom proxy-handler contracts. Not a drop-in result established by this review. [D1, R2, R7–R10] |
| Use native SDK/HTTP adapters | **[INFERENCE]** Strongest route toward eliminating the gateway dependency and keeping provider exceptions closer to the debugger. Canary already maintains much of the image-provider logic, but the native calls currently execute inside custom proxy handlers. Removing the gateway relocates alias resolution, authentication, normalization, costs, and provider error semantics; it does not delete those responsibilities. [R3, R7–R9, R13] |

The custom Vertex exception translation is a concrete example: it preserves quota/status errors across the gateway boundary. The manifest, reference-order, geometry, and output-shape checks are another. Those behaviors must survive any transport replacement; a generic “OpenAI-compatible” endpoint claim is insufficient. [R7]

[INFERENCE] There is no observability-based reason to make LiteLLM a permanent architectural requirement. There is also not enough evidence here to recommend an immediate full gateway rewrite as the fastest way to improve this development loop. Better application evidence has value with either transport choice.

## What the recommended developer loop should reveal

These are decision criteria for the desired experience, not an implementation plan:

- Which job, stage/page, request, and logical model call failed; which attempt and phase was active.
- Whether the cause was transport/quota, refusal, malformed output, validation, artifact persistence, or post-render analysis—not just a generic gateway error.
- Which request fingerprint and saved artifacts explain the failure, without requiring unrestricted prompt/image export.
- Whether a paid result already exists, whether submission outcome is unknown, and which recovery action preserves that work. Keep the existing no-ambiguous-resubmission rule for complete pages. [R4, R11, R17, R21]
- Whether telemetry delivery failed, without making the viewer responsible for billing correctness or workflow state. [R5, R6, R13]

**Bottom line:** the current live transport dependency is justified by existing integration behavior; an observability dependency on LiteLLM is not. Favor local-first, application-owned evidence, optional general-purpose tracing, and recovery tied to Canary's artifacts/state. Production dashboards, alerting, retention, and deployment design are deliberately deferred.

## Implementation status (separate from the historical review above)

The sections above describe the repository as inspected before implementation.
The implemented development baseline is:

- `CANARY_LOCAL_DIAGNOSTICS=1` enables bounded failure records at
  `<project>/.canary/diagnostics.jsonl` (new files mode `0600`) and traceback
  details in stage state/API responses. It is disabled in production.
  `scripts/dev.sh` enables it when starting the backend.
- `CANARY_OTEL_ENABLED=1 CANARY_OTEL_CONSOLE=1` selects console stage spans
  instead of OTLP. Both are optional; no telemetry backend is required.
- API logs include request IDs. Stage journals inherit available request,
  project, job, and stage IDs. UI load failures and stage failures show their
  actual errors; in-progress missing artifacts retain their progress state.
- The launcher rejects incompatible pipeline contracts without stopping the
  existing process. Extract logs describe automatic Brief chaining, not approval.
- Usage database operations run off the event loop but remain awaited before
  returning; terminal writes are protected from cancellation races.
- Langfuse still requires credentials and a host. HTTP delivery failures are
  logged; prompt/response payloads are redacted by default. The existing
  `CANARY_LOG_INCLUDE_PROMPTS=1` flag explicitly permits their export.

No provider routes, approvals, or production deployments were changed.

## Verification and limitations

Verification used local deterministic fixtures, not live model calls:
backend regression tests, frontend tests/build/lint, launcher stale-contract
checks, and a runtime failure/recovery smoke scenario. A real Chromium tab
rendered the actual fallback components with synthetic state and API requests
blocked; failure disclosure, running progress, and the 404 panel were visually
confirmed. This was not an authenticated end-to-end project run.

Historical citation ranges refer to the reviewed snapshot, not an immutable
commit. No comparative timings, live provider compatibility trial, production
deployment, or provider benchmark was performed.

Privacy limits: the journal excludes request bodies and image bytes, but
traceback and exception text can still carry source content or paths, so
records must be inspected before sharing. There is no prompt-free guarantee
for exception text.

Verification passed: backend suite (968 passed, 4 skipped), frontend suite
(256 passed), frontend build/lint, Python compilation, shell syntax, and the
documentation reliability check. A deterministic HTTP 401 smoke confirmed
that optional Langfuse rejection is logged without raising into the workflow.
OpenTelemetry is not installed in the local environment: its graceful
disabled path was exercised, but actual console span emission was not.

## Repository evidence

- **R1 — text gateway path:** [base URL selection](novel_to_comic/src/novel_to_comic/ai/client.py#L504-L520); [chat request submission](novel_to_comic/src/novel_to_comic/ai/client.py#L1385-L1451).
- **R2 — Style/Cast transport coupling:** [selector](novel_to_comic/src/novel_to_comic/ai/providers/selector.py#L10-L19); [wire adapter type requirement](novel_to_comic/src/novel_to_comic/ai/client.py#L1605-L1648); [image HTTP transport](novel_to_comic/src/novel_to_comic/ai/providers/litellm_http.py#L43-L100).
- **R3 — aliases and gateway policy:** [text/provider aliases](litellm/config.yaml#L1-L113); [image aliases, disabled callbacks, retry setting, custom providers](litellm/config.yaml#L115-L163).
- **R4 — complete-page gateway and finalization:** [request, transport, and finalized generation](novel_to_comic/src/novel_to_comic/page_drawing.py#L593-L726).
- **R5 — application event persistence:** [started event](novel_to_comic/src/novel_to_comic/ai/client.py#L793-L828); [final event, metrics, persistence, settlement gate](novel_to_comic/src/novel_to_comic/ai/client.py#L831-L968).
- **R6 — direct optional Langfuse emission:** [configuration gate](novel_to_comic/src/novel_to_comic/ai/client.py#L977-L984); [HTTP ingestion and event construction/scheduling](novel_to_comic/src/novel_to_comic/ai/client.py#L1002-L1137).
- **R7 — custom native Vertex behavior:** [error translation](litellm_handlers/vertex_multimodal.py#L83-L114); [manifest checks, native request, response normalization](litellm_handlers/vertex_multimodal.py#L206-L352).
- **R8 — custom fal behavior:** [queued image lifecycle](litellm_handlers/fal_provider.py#L109-L135); [submit/poll/fetch/download](litellm_handlers/fal_provider.py#L268-L327).
- **R9 — custom Reve behavior:** [manifest and v2 generation](litellm_handlers/reve_provider.py#L133-L183); [reference payload and response normalization](litellm_handlers/reve_provider.py#L264-L308).
- **R10 — dependency placement:** [application dependencies and optional OTel](novel_to_comic/pyproject.toml#L1-L39); [gateway image and SDK override](litellm/Dockerfile#L1-L8).
- **R11 — application transport retry policy:** [pacing, retry loop, ambiguous-submission guard](novel_to_comic/src/novel_to_comic/ai/client.py#L152-L265).
- **R12 — parsing and schema recovery:** [JSON parsing after completion](novel_to_comic/src/novel_to_comic/ai/client.py#L1246-L1334); [validation/local repair/re-prompt loop](novel_to_comic/src/novel_to_comic/clients/structured_call.py#L97-L181).
- **R13 — costs and ledger:** [response cost extraction](novel_to_comic/src/novel_to_comic/ai/client.py#L622-L647); [cached pricing](novel_to_comic/src/novel_to_comic/model_costs.py#L34-L63); [ledger settlement](novel_to_comic/src/novel_to_comic/ai/client.py#L1140-L1193).
- **R14 — local startup modes:** [defaults/options](scripts/dev.sh#L14-L41); [live, replay, optional observability](scripts/dev.sh#L181-L242).
- **R15 — local infrastructure configuration:** [LiteLLM and its Postgres](docker-compose.yml#L68-L126); [Langfuse services](docker-compose.yml#L128-L260).
- **R16 — text visibility and success timing:** [prompt payload and issued breadcrumb](novel_to_comic/src/novel_to_comic/ai/client.py#L1407-L1438); [success finalized before return](novel_to_comic/src/novel_to_comic/ai/client.py#L1514-L1535); [stream progress](novel_to_comic/src/novel_to_comic/ai/client.py#L334-L465).
- **R17 — durable page lifecycle:** [request, render, provenance, then analysis](novel_to_comic/src/novel_to_comic/page_drawing.py#L729-L816).
- **R18 — local logger and request correlation:** [Rich configuration](novel_to_comic/src/novel_to_comic/server/logging.py#L24-L74); [request middleware](novel_to_comic/src/novel_to_comic/server/logging.py#L109-L166).
- **R19 — existing OTel and older API logging:** [opt-in trace exporter](novel_to_comic/src/novel_to_comic/server/telemetry.py#L21-L62); [provider span exclusions](novel_to_comic/src/novel_to_comic/clients/api_logging.py#L108-L151); [prompt opt-in](novel_to_comic/src/novel_to_comic/clients/api_logging.py#L190-L212); [AI correlation metadata](novel_to_comic/src/novel_to_comic/ai/client.py#L577-L601).
- **R20 — worker failure evidence:** [job outcomes and optional tracebacks](novel_to_comic/src/novel_to_comic/server/generation_jobs.py#L184-L276).
- **R21 — recovery ownership:** [failed-stage reset/error endpoints](novel_to_comic/src/novel_to_comic/server/routers/pipeline.py#L561-L612); [analysis-only failure distinction](novel_to_comic/src/novel_to_comic/server/routers/pages.py#L77-L95).
- **R22 — synchronous application database:** [Supabase client and timeout](novel_to_comic/src/novel_to_comic/server/db.py#L21-L34).
- **R23 — shared HTTP pool:** [model timeout/pool configuration](novel_to_comic/src/novel_to_comic/ai/client.py#L496-L501).

## Primary documentation

- **D1:** [LiteLLM SDK versus Proxy](https://docs.litellm.ai/docs/) — separate deployment choices, normalization, exceptions, and gateway capabilities.
- **D2:** [LiteLLM virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys) — Postgres requirement for virtual-key management.
- **D3:** [OpenTelemetry Python instrumentation](https://opentelemetry.io/docs/languages/python/instrumentation/) — explicit spans, events, links, and exception recording.
- **D4:** [OpenTelemetry Python exporters](https://opentelemetry.io/docs/languages/python/exporters/) — console export without a telemetry backend and OTLP export.
- **D5:** [Logfire with standard OTel clients](https://pydantic.dev/docs/logfire/guides/alternative-clients/) — Python OTLP integration, endpoint, authentication, and service identity.
- **D6:** [Logfire Live view](https://pydantic.dev/docs/logfire/observe/live/) — trace navigation, SQL filtering, attributes, and exception detail.
- **D7:** [Logfire HTTPX instrumentation](https://pydantic.dev/docs/logfire/integrations/http-clients/httpx/) — outbound HTTP coverage, completion visibility, optional body/header capture.
- **D8:** [Logfire manual tracing](https://pydantic.dev/docs/logfire/instrument/python/add-manual-tracing/) — nested context and explicit handling of caught exceptions.
- **D9:** [Logfire scrubbing](https://pydantic.dev/docs/logfire/instrument/python/scrubbing/) — scrubbing limitations, especially LLM content and preformatted messages.

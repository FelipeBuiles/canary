# AI Gateway Migration with LiteLLM Proxy

**Date:** 2026-04-29
**Status:** Draft

## Overview

Canary currently calls AI providers through local provider wrappers under
`novel_to_comic.clients`. That code already gives the project a useful seam, but
the app still knows about provider SDKs, provider API keys, provider-specific
cost math, and provider-specific request telemetry.

This design moves all runtime AI calls behind a centralized LiteLLM Proxy:

`Canary app -> internal AI client -> ai_usage_events ledger -> LiteLLM Proxy -> providers -> Langfuse`

The migration is intentionally not a wholesale rewrite of every stage. The
first implementation introduces a small internal AI client and moves calls
through it while preserving the existing stage boundaries and pipeline state
contracts.

## Current Provider Surface

Direct provider integration is concentrated in these files:

- `novel_to_comic/src/novel_to_comic/clients/text.py`
  - Routes text/JSON requests by model.
- `novel_to_comic/src/novel_to_comic/clients/gemini.py`
  - Uses `google-genai` for Gemini text and Vertex AI.
- `novel_to_comic/src/novel_to_comic/clients/claude.py`
  - Uses `anthropic.AsyncAnthropic`.
- `novel_to_comic/src/novel_to_comic/clients/openai_text.py`
  - Uses `openai.AsyncOpenAI`.
- `novel_to_comic/src/novel_to_comic/clients/openrouter_text.py`
  - Uses `openai.AsyncOpenAI` with OpenRouter's OpenAI-compatible base URL.
- `novel_to_comic/src/novel_to_comic/clients/_openai_compat.py`
  - Shared OpenAI-compatible chat completion implementation.
- `novel_to_comic/src/novel_to_comic/clients/flux.py`
  - Routes image generation to Gemini native, OpenAI, OpenRouter, or Together.
- `scripts/test_fal_lora.py`
  - Experimental direct fal.ai calls.
- `scripts/test_replicate_pulid.py`
  - Experimental direct Replicate calls.

Primary app call sites already use `clients.text` or `clients.flux` rather than
provider SDKs directly:

- Stage 1 extraction calls `text.generate_json`.
- Stage 3 screenplay adaptation calls `text.generate_json`.
- Stage 4 layout planning calls `clients.text.generate_json`.
- Stage 2 cast/reference generation calls `flux.generate_image`.
- Stage 7 draw generation calls `flux.generate_image_multi_ref`.
- Project covers, style samples, lettering style generation, text translation,
  and prompt rewrite routes call the same wrappers.

## Goals

- Centralize all runtime AI calls through LiteLLM Proxy.
- Add a small internal AI client with:
  - `generateText()`
  - `generateStructuredObject()`
  - `generateImage()`
- Create an `ai_usage_events` row before every AI request.
- Finalize each event after success, refusal, cancellation, or failure.
- Store model alias, resolved model/provider when available, feature, user,
  project/workspace, sanitized params, latency, usage, cost fields,
  provider response id, and error details.
- Pass useful metadata to LiteLLM and Langfuse.
- Stop Canary runtime code from knowing provider API keys.
- Use gateway model aliases in app config rather than provider model names.
- Keep provider-specific behavior isolated behind the AI client and LiteLLM
  config.
- Preserve existing pipeline stage boundaries and stage output contracts.
- Keep `credit_ledger` as the billing ledger and add `ai_usage_events` as the
  request observability ledger.

## Non-Goals

- Rewriting all stage logic at once.
- Moving source text, full prompts, or provider responses into Canary's app DB.
- Exposing LiteLLM or provider keys to frontend code.
- Replacing general OpenTelemetry infrastructure with Langfuse.
- Keeping Gemini native image multi-reference behavior in the first gateway
  implementation if it requires non-OpenAI-compatible LiteLLM endpoints.
- Adding backward-compatible provider-key request paths after the gateway path
  is active.

## Core Decisions

- `ai_usage_events` is separate from `credit_ledger`.
- `credit_ledger` remains the user billing and credit reservation ledger.
- `ai_usage_events` records every attempted AI request, including failures and
  refusals.
- Pipeline/request context uses a small `contextvars` scope so stages do not
  need `user_id` and `project_id` threaded through every signature.
- Feature names are still passed explicitly at AI call sites over time.
- All runtime AI calls migrate through LiteLLM in the first implementation,
  including images.
- Images use OpenAI-compatible LiteLLM endpoints first, especially
  `/v1/images/generations` and `/v1/images/edits` where supported.
- App config uses gateway aliases such as `canary/extract` and
  `canary/image-primary`, not provider model names.
- Canary stops knowing provider API keys for runtime AI calls.
- `ai_usage_events` stores redacted params, hashes, sizes, ids, usage, cost
  fields, and errors. Full prompt/response debugging moves to Langfuse.
- Failed/refused request billing is configurable.
- Default failure billing policy is provider-usage-only.
- Structured outputs use both gateway JSON/schema support and app-side Pydantic
  validation/retry.

## Proposed Architecture

### Internal AI Client

Add an internal module under:

- `novel_to_comic/src/novel_to_comic/ai/client.py`

The module exposes:

```python
async def generateText(...): ...
async def generateStructuredObject(...): ...
async def generateImage(...): ...
```

The public functions should return the existing `ApiResult[T]` shape at first
so the stage state and credit settlement code can migrate incrementally.

The client owns:

- LiteLLM base URL and API key usage.
- OpenAI-compatible HTTP requests.
- Event creation and finalization.
- Metadata sent to LiteLLM/Langfuse.
- Response id extraction.
- Usage extraction.
- Refusal/failure classification.
- Translation from gateway response to existing `UsageRecord`.
- Redacted structured logging.

The client should use `httpx.AsyncClient` directly or the OpenAI SDK configured
with `base_url=config.litellm_base_url`. Direct `httpx` is preferable for the
first version because the ledger finalization code can capture raw status codes,
response ids, and error bodies consistently for both chat and image endpoints.

### AI Request Context

Add a small context module, for example:

```python
@dataclass(frozen=True)
class AIRequestContext:
    user_id: str | None
    project_id: str | None
    project_name: str | None
    workspace_id: str | None
    stage: str | None
    request_id: str | None
```

Use `contextvars.ContextVar` plus a context manager:

```python
with ai_request_context(...):
    await _run_stage(...)
```

Server routes that call AI outside stage execution should either set the
context around the call or pass equivalent context directly into the AI client.

### PDF Extraction Compatibility

Stage 1 currently supports image-based PDFs by passing PDF bytes directly to
Gemini native processing. That behavior does not fit the first gateway rule:
all app AI calls use LiteLLM through OpenAI-compatible HTTP endpoints.

The implementation must choose one of these compatible paths before runtime
provider SDK removal:

- Extract text locally with `pypdf` when possible and send text through
  `generateStructuredObject()`.
- For image-based PDFs, either fail with a clear unsupported-input error or add
  a separate OCR/preprocessing step that also goes through an OpenAI-compatible
  LiteLLM endpoint.

Do not keep a hidden Gemini-native PDF fallback in Canary app code.

### Model Aliases

Canary config should use intent-level aliases:

- `canary/extract`
- `canary/screenplay`
- `canary/panel`
- `canary/prompt`
- `canary/image-primary`
- `canary/image-fast`

Existing fields can remain temporarily but their defaults should become aliases:

- `extraction_model: "canary/extract"`
- `screenplay_model: "canary/screenplay"`
- `panel_model: "canary/panel"`
- `prompt_model: "canary/prompt"`
- `image_model: "canary/image-primary"`
- `fallback_image_model: "canary/image-fast"`

Provider-specific model names move to `litellm/config.yaml`.

### LiteLLM Request Metadata

Every request should include metadata for Langfuse/LiteLLM grouping:

- `generation_name`: feature name, such as `extract.story_bible`.
- `trace_id`: app request id or generated AI event id.
- `session_id`: project id or project key.
- `user_id`: authenticated user id.
- `tags`: environment, stage, operation, feature.
- `metadata`: project name, stage, operation, event id, model alias, retry
  attempt, dev mode, language.

Prompt text should not be stored in `ai_usage_events`. Prompt hashes and size
metrics are enough for reconciliation. Langfuse owns prompt/response debugging.

## Database Design

Add an `ai_usage_events` table to `docs/supabase-schema.sql`.

Recommended fields:

- `id uuid primary key default gen_random_uuid()`
- `created_at timestamptz not null default now()`
- `started_at timestamptz not null default now()`
- `finished_at timestamptz`
- `user_id uuid references auth.users(id) on delete cascade`
- `project_id uuid references public.projects(id) on delete set null`
- `workspace_id text`
- `project_name text`
- `stage text`
- `feature text not null`
- `operation text not null`
- `status text not null`
- `billable boolean not null default false`
- `billing_policy text`
- `model_alias text not null`
- `provider text`
- `provider_model text`
- `litellm_model text`
- `provider_response_id text`
- `request_id text`
- `idempotency_key text unique`
- `input_tokens integer not null default 0`
- `output_tokens integer not null default 0`
- `total_tokens integer not null default 0`
- `image_count integer not null default 0`
- `latency_ms integer`
- `cost_usd numeric(12, 6)`
- `cost_source text`
- `params_json jsonb not null default '{}'::jsonb`
- `request_summary_json jsonb not null default '{}'::jsonb`
- `usage_json jsonb not null default '{}'::jsonb`
- `metadata_json jsonb not null default '{}'::jsonb`
- `error_type text`
- `error_message text`
- `error_json jsonb not null default '{}'::jsonb`

Status values:

- `started`
- `succeeded`
- `failed`
- `refused`
- `cancelled`

Indexes:

- `(user_id, created_at desc)`
- `(project_id, created_at desc)`
- `(status, created_at desc)`
- `(feature, created_at desc)`
- unique `idempotency_key` where not null
- optional unique `provider_response_id` where not null

RLS:

- Enable RLS.
- Authenticated users can select only their own rows.
- Backend service role writes all rows.

## Billing and Credits

`credit_ledger` remains the billing ledger. `ai_usage_events` does not replace
credit reservations or settled credit rows.

The AI client finalizes `ai_usage_events`. Billing settlement should consume
the finalized event and then write `credit_ledger` rows, either immediately or
through existing stage settlement flows.

Failure billing policy:

- `AI_BILL_FAILED_REQUESTS=provider_usage_only` by default.
- `AI_BILL_FAILED_REQUESTS=never` disables failed/refused request billing.
- `AI_BILL_FAILED_REQUESTS=estimate_all` allows estimated billing for failed
  provider refusals or failures when provider usage is unavailable.

Default behavior:

- Successful requests are billable when usage/cost or image count is present.
- Failed or refused requests are billable only when the provider or LiteLLM
  reports usage/cost.
- Network errors, timeouts before provider acceptance, and gateway auth errors
  should not be billable without provider-reported usage.

Refusals should be stored as `status='refused'`, not generic `failed`, when the
gateway/provider indicates a content-policy or safety refusal.

## OpenTelemetry, Grafana, and Langfuse Split

Keep as infrastructure observability:

- `server/telemetry.py`
- general OTLP export setup
- request/job/stage logs
- non-prompt operational spans

Move to Langfuse/LiteLLM:

- LLM prompt/response debugging
- provider model latency
- token usage
- image generation usage
- provider response ids
- per-model cost and spend tracing
- prompt metadata and feature-level generation traces

Refactor:

- `clients/api_logging.py` should stop creating provider-specific LLM spans
  once the AI client and LiteLLM/Langfuse path is active.
- Keep redacted console/app logs for developer ergonomics.
- Keep `CANARY_LOG_INCLUDE_PROMPTS` and `CANARY_LOG_FULL_PROMPTS` off by
  default; consider deprecating full prompt logging once Langfuse is configured.

## Environment Variables

Add backend-only variables to `.env.example`:

- `LITELLM_BASE_URL=http://localhost:4000`
- `LITELLM_API_KEY=sk-local-canary`
- `AI_BILL_FAILED_REQUESTS=provider_usage_only`

LiteLLM service variables:

- `LITELLM_MASTER_KEY=sk-local-canary`
- `LITELLM_SALT_KEY=<local-dev-secret>`
- `OPENAI_API_KEY=`
- `ANTHROPIC_API_KEY=`
- `GEMINI_API_KEY=`
- `OPENROUTER_API_KEY=`
- `TOGETHER_API_KEY=`
- `VERTEXAI_PROJECT=`
- `VERTEXAI_LOCATION=global`
- `LANGFUSE_PUBLIC_KEY=`
- `LANGFUSE_SECRET_KEY=`
- `LANGFUSE_HOST=http://langfuse-web:3000`

Provider API keys should be removed from Canary runtime config and docs over the
migration. They should exist only in the LiteLLM service environment.

Frontend `.env.example` should not gain any provider or LiteLLM keys.

## Docker Compose

Add a root `docker-compose.yml` or compose override with:

- `litellm`
  - image `docker.litellm.ai/berriai/litellm:main-latest`.
  - mounts `./litellm/config.yaml:/app/config.yaml`.
  - exposes `4000`.
  - depends on its own Postgres if spend tracking/UI needs persistence.
- `langfuse-web`
- `langfuse-worker` if required by the selected Langfuse version.
- `langfuse-postgres`
- `langfuse-clickhouse` and object storage/redis if required by the selected
  Langfuse deployment profile.

Use the official current Langfuse compose shape during implementation rather
than hand-rolling service internals from memory.

## Sample LiteLLM Config

Add `litellm/config.yaml` with aliases for current model intents.

Initial example shape:

```yaml
model_list:
  - model_name: canary/extract
    litellm_params:
      model: vertex_ai/gemini-3.1-pro-preview
      vertex_project: os.environ/VERTEXAI_PROJECT
      vertex_location: os.environ/VERTEXAI_LOCATION

  - model_name: canary/screenplay
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

  - model_name: canary/panel
    litellm_params:
      model: openai/gpt-5.4-mini
      api_key: os.environ/OPENAI_API_KEY

  - model_name: canary/prompt
    litellm_params:
      model: vertex_ai/gemini-3.1-flash-lite-preview
      vertex_project: os.environ/VERTEXAI_PROJECT
      vertex_location: os.environ/VERTEXAI_LOCATION

  - model_name: canary/image-primary
    litellm_params:
      model: openai/gpt-image-1
      api_key: os.environ/OPENAI_API_KEY

  - model_name: canary/image-fast
    litellm_params:
      model: openrouter/google/gemini-2.5-flash-image
      api_key: os.environ/OPENROUTER_API_KEY

litellm_settings:
  callbacks: ["langfuse"]
  set_verbose: false

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
```

Model names and provider prefixes must be verified against the installed
LiteLLM version during implementation. If a listed current model is not
supported by LiteLLM under that exact name, the config should preserve the
alias and change only the `litellm_params.model` route.

## Image Migration Constraints

The first image migration uses OpenAI-compatible image endpoints. This means:

- Current Gemini native `generate_content` multi-reference behavior is not
  preserved if it requires `/generateContent`.
- The AI client should support:
  - text-to-image via `/v1/images/generations`
  - image edit/reference calls via `/v1/images/edits` where LiteLLM and the
    selected provider support them.
- If a provider/model cannot support the existing reference-image pattern
  through OpenAI-compatible endpoints, the selected gateway alias should route
  to a model that can.
- Visual continuity behavior must be tested after migration.
- Stage 2 and Stage 7 should keep text prompt authority and continue to avoid
  generated text inside images.

The old `flux.py` capability checks can either move into the AI image client or
be retired as aliases settle on gateway-supported models. Provider-specific
branches should not leak back into stage code.

## Structured Output Strategy

`generateStructuredObject()` should:

- accept system prompt, user content, model alias, feature, temperature,
  max output tokens, optional JSON schema, and optional Pydantic model type;
- request JSON mode or JSON schema through OpenAI-compatible `response_format`
  when supported;
- parse JSON in the app;
- return `ApiResult[dict]` or a validated object;
- preserve existing normalization and validation logic in stages;
- keep existing retry-on-validation-error behavior where already present.

Schema enforcement at the gateway reduces malformed output. App-side Pydantic
validation remains the authoritative pipeline contract.

## Migration Phases

### Phase 1: Infrastructure and Ledger

- Add `ai_usage_events` schema.
- Add contextvars request context.
- Add LiteLLM env vars to backend config loading.
- Add `AI_BILL_FAILED_REQUESTS`.
- Add Docker Compose services.
- Add sample LiteLLM config.
- Keep old providers untouched until the client exists.

### Phase 2: Internal AI Client

- Add the new AI client module.
- Implement chat/text request support.
- Implement structured JSON request support.
- Implement image generation/edit support through OpenAI-compatible LiteLLM
  endpoints.
- Implement event create/finalize around every request.
- Implement metadata propagation to LiteLLM/Langfuse.
- Convert gateway responses into `ApiResult` and `UsageRecord`.

### Phase 3: Replace Local Provider Wrappers

- Point `clients.text.generate_json` and `generate_text` to the AI client.
- Point `clients.flux.generate_image` and `generate_image_multi_ref` to the AI
  client.
- Keep thin compatibility wrappers so stages do not all change at once.
- Remove direct provider SDK imports from active runtime paths.
- Keep experimental scripts out of runtime migration unless they are promoted.

### Phase 4: Billing Integration

- Settle successful usage events into `credit_ledger`.
- Apply configurable failed/refused billing.
- Ensure duplicate settlement is prevented by event id or idempotency key.
- Preserve stage reservations and releases.
- Keep `state.json` usage summaries compatible with existing UI status.

### Phase 5: Telemetry Cleanup

- Remove provider-specific LLM span creation from `api_logging.py`.
- Keep general OTel bootstrap for infrastructure observability.
- Move prompt/response/cost debugging to Langfuse.
- Update docs to explain the new split.

### Phase 6: Provider Key Cleanup

- Remove runtime provider key fields from `Config`.
- Update `save_config()` comments and `.env.example`.
- Ensure config API still masks or ignores any deprecated provider key fields
  during the transition.
- Verify frontend never sees provider or LiteLLM secrets.

## Verification Plan

- Unit test AI event creation/finalization for success, failure, refusal, and
  cancellation.
- Unit test failure billing policy:
  - `provider_usage_only`
  - `never`
  - `estimate_all`
- Unit test metadata construction without prompt leakage.
- Unit test structured JSON parsing and usage extraction.
- Unit test image response decoding for `b64_json` and URL responses if both
  are supported.
- Integration test LiteLLM chat completions against a local proxy when
  available.
- Integration test LiteLLM image generation against a configured local proxy
  when provider keys are available.
- Run a small project through extract, adapt, plan, cast, draw, and compose.
- Confirm `ai_usage_events` rows exist for every AI attempt.
- Confirm `credit_ledger` only receives rows allowed by billing policy.
- Confirm Langfuse receives traces with user/project/stage/feature metadata.
- Confirm no provider API keys are returned by backend config APIs or bundled
  into frontend code.

## Open Risks

- LiteLLM model names for preview/current models may differ from Canary's
  current names.
- OpenAI-compatible image endpoints may not preserve current Gemini native
  multi-reference behavior.
- Provider refusal shapes vary; refusal classification will need conservative
  matching plus provider/gateway response inspection.
- LiteLLM-reported cost may not be available for every provider/model; app cost
  estimates may remain a fallback.
- Local Langfuse deployment requirements may add services beyond a simple
  two-container compose setup.

## Implementation Success Criteria

- Runtime provider SDK/API calls no longer happen from Canary app code.
- All app AI calls go through the internal AI client.
- All internal AI client requests go through LiteLLM using OpenAI-compatible
  HTTP endpoints.
- Every AI request creates and finalizes an `ai_usage_events` row.
- Gateway aliases are used in app config.
- Provider API keys live only in LiteLLM service configuration/environment.
- Existing stage outputs and pipeline status behavior remain intact.
- Billing remains separated from request observability.
- Langfuse owns LLM trace/cost/debugging details.
- OTel remains available for non-LLM infrastructure observability.

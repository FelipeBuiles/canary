# Labs Phase 0+1 Design

Date: 2026-05-13

## Status

Approved for implementation planning.

## Scope

Implement the Labs follow-up foundation and Seedream promotion work together:

- Phase 0: split production image generation into a provider layer, explicit
  reference roles, and shared finalisation/accounting.
- Phase 1: promote Seedream V4.5 Edit to the production balanced image tier if
  the LiteLLM-first path preserves multi-reference quality.

This spec intentionally does not preserve internal legacy image-reference call
paths. Breaking internal API changes are acceptable when they produce a simpler
provider boundary. Public HTTP behavior and user-visible pipeline behavior must
remain stable unless Phase 1 explicitly changes the balanced image model.

## Goals

- Preserve current LiteLLM image-generation behavior while extracting it from
  `ai/client.py`.
- Make image references role-aware before they reach the provider layer.
- Keep cost tracking, billing rows, failed-request policy, and Langfuse output
  equivalent to today.
- Add Labs prompt A/B mode so prompt-rendering experiments can run against a
  single model.
- Test Seedream through LiteLLM first and only add a custom LiteLLM provider
  plugin if built-in `fal_ai/*` routing fails or drops multi-ref conditioning.

## Non-Goals

- Do not implement Phase 2 prompt prose generation in this pass.
- Do not implement the native Gemini path from Phase 3.
- Do not add app-side direct fal production routing unless the LiteLLM plugin
  path is rejected during Phase 1 validation.
- Do not add compatibility shims for old internal provider parameters.

## Architecture

Production image generation is split into three layers.

### Client Orchestrator

`novel_to_comic/ai/client.py` keeps the public `generate_image()` entry point
but no longer owns provider HTTP details. It must:

- build the event ID, operation metadata, pre-call estimate, and request summary;
- call `selector.pick(model_alias, config)` to get an `ImageProvider`;
- pass a normalized `list[RefImage]` to the provider;
- write the returned image bytes to `output_path`;
- call finalisation for success, refusal, cancellation, and failure cases;
- return `ApiResult[Path]`.

### Provider Layer

Create `novel_to_comic/ai/providers/`.

`base.py` defines:

- `RefImage`: `path: Path`, `role: Literal["subject", "style", "continuity", "location_plate", "prop"]`.
- `ProviderRawResult`: image bytes, mime type, latency, raw response, response
  headers, provider request ID, and optional provider-reported cost.
- `ImageProvider`: async protocol for `generate(...)`.

`litellm_http.py` implements today's LiteLLM HTTP image request shape. It owns:

- OpenAI-compatible size coercion;
- `quality` request parameter handling;
- `/v1/images/generations` vs `/v1/images/edits` dispatch;
- multipart `image` file construction;
- HTTP retry through the existing `_post_with_retry` helper;
- refusal detection;
- image response decoding.

For Phase 0, this provider flattens `RefImage` roles back into anonymous
OpenAI-compatible `image` multipart parts. The flattening order is stable:
subject and prop refs first, then continuity, style, and location refs. This
preserves today's behavior as closely as possible while keeping role information
available for Phase 1+ provider-specific decisions.

`selector.py` initially returns `LitellmHttpProvider` for all models. Phase 1
keeps this selector trivial when Seedream can route through LiteLLM config or a
LiteLLM plugin.

### Finalisation Layer

Create `novel_to_comic/ai/finalisation.py` for image-call accounting. It owns:

- `ai_usage_events` insert/finalize calls;
- request summary and redacted parameter storage;
- usage extraction from provider raw response and response headers;
- failed-request billing policy;
- pricing estimate drift metadata;
- Langfuse generation logging;
- `ApiResult[Path]` assembly.

The finalisation layer can reuse existing helper functions from `ai/client.py`,
but the implementation moves image-specific accounting out of the HTTP provider.
Text-generation behavior must remain unchanged.

## Reference Data Flow

`s7_draw.resolve_panel_reference_paths()` is replaced with
`resolve_panel_references()` and returns `list[RefImage]`.

Role assignment rules:

- prompt `reference_image_paths` become `subject` by default;
- prop refs become `prop` when the path structure identifies a prop reference;
- previous panel images become `continuity`;
- selected style sample images become `style`;
- location plates become `location_plate`.

Model-aware capping happens after role assignment:

- GPT Image 2 (`image-quality`, `openai/gpt-image-2`, `gpt-image-2`) keeps the
  current minimal subject behavior and skips style/location/continuity refs.
- Seedream gets up to 10 refs, preserving subject/prop priority before
  continuity/style/location refs.
- Default models keep the current broad behavior with all applicable refs.

`clients/flux.generate_image_multi_ref()` accepts rich `refs` and passes them
through to `ai.generate_image()`. Internal callers use the rich reference
contract instead of passing separate subject/style lists.

Cost estimation for draw-stage panels must call the same
`resolve_panel_references()` function and count the resulting refs.

## Labs Prompt A/B

Labs gets a prompt-comparison mode for Phase 2 validation.

Backend changes:

- `LabsPanelSpec` gains `prompt_variant_b: str | None`.
- `LabsRunSpec` records whether prompt comparison mode is active.
- The runner expands comparison-mode panels into variant rows: variant `A`
  uses `prompt`, variant `B` uses `prompt_variant_b`.
- Cell storage becomes variant-aware so `Panel 1 / A` and `Panel 1 / B` do not
  overwrite each other.
- The run manifest stores both prompts and `prompt_compare_mode`.
- Normal mode remains the default and stores only variant `A`.

Frontend changes:

- Add a "Compare two prompts" toggle near model selection.
- When enabled, restrict model selection to one model.
- Show two prompt textareas per panel.
- Render result rows as panel plus variant, e.g. `Panel 1 / A` and
  `Panel 1 / B`.
- Keep the lightbox prompt display variant-specific.

## Phase 1 Seedream Flow

Phase 1 begins after the Phase 0 provider split and reference-role migration
are passing tests.

### Gate 1: Built-In LiteLLM fal Provider

Add a temporary `image-balanced-seedream-test` alias pointing at
`fal_ai/bytedance/seedream/v4.5/edit`, then run a real multi-reference
image-edit request through `http://localhost:4000/v1/images/edits`.

Accept Option A if:

- an image is returned;
- multiple reference images visibly affect the result;
- response headers/usage still produce cost ledger and Langfuse parity.

If accepted, permanent implementation is:

- change `image-balanced` in `litellm/config.yaml` to Seedream;
- keep the prior Gemini Pro alias under a rollback name such as
  `image-balanced-gemini`;
- ensure pricing overrides map `image-balanced` and/or the provider model to
  `$0.04/image`;
- add Seedream-specific 10-ref cap behavior;
- bump generation-job timeout if real draw runs exceed the current default.

### Gate 2: LiteLLM Custom fal Plugin

If built-in LiteLLM routing fails or drops multi-ref conditioning, add a custom
LiteLLM provider plugin under `litellm_handlers/`.

`fal_provider.py` ports the known-good Labs fal queue flow:

- submit JSON payloads to `https://queue.fal.run/{endpoint}`;
- send refs as data URIs in `image_urls`;
- poll `status_url`;
- fetch `response_url`;
- download the image;
- return an OpenAI-shaped image response with `b64_json`.

Wire it through:

- `docker-compose.yml` volume mount for `litellm_handlers`;
- `PYTHONPATH` including the handler directory;
- `litellm_settings.custom_provider_map`;
- `image-balanced` alias pointing at the custom provider model.

Add a smoke script under `novel_to_comic/scripts/` that hits the local LiteLLM
proxy and verifies a real Seedream image response.

### Direct Provider Fallback

Only implement `ai/providers/fal_native.py` if the custom LiteLLM plugin path
is rejected for operational reasons. If that happens, the direct provider must
still return `ProviderRawResult` and let `finalisation.py` handle all tracking.

## Testing

Backend tests:

- no-ref LiteLLM image request uses `/v1/images/generations` with today's JSON
  shape;
- multi-ref LiteLLM image request uses `/v1/images/edits` with today's
  multipart shape;
- provider extraction preserves b64 image decoding and file writes;
- finalisation preserves success, refusal, cancel, and failed-request billing
  behavior;
- reference resolution asserts role, order, and cap behavior for GPT Image 2,
  Seedream, and default models;
- panel image cost estimation counts the same refs that draw uploads;
- Labs manifest/storage/API support normal mode and A/B variant mode.

Frontend tests/build:

- TypeScript types cover `prompt_variant_b`, `prompt_compare_mode`, and
  variant cells.
- Labs page builds with normal mode and A/B mode.

Verification commands:

```bash
rtk uv run pytest novel_to_comic/tests/
```

Run the repo's existing web build/test command after frontend changes.

Manual validation:

- Run Labs A/B prompt mode against a cheap/fast model and verify two variants
  render for one panel.
- Run the Seedream LiteLLM pre-flight with at least three refs: two subject refs
  and one location/style ref.
- Before flipping `image-balanced`, compare current Gemini Pro vs Seedream on
  2-3 real scenes and ship only when Seedream is equal or better on at least
  6/8 panels by user review.

## Acceptance Criteria

- `ai/client.py:generate_image()` is no longer a monolithic HTTP function.
- Production draw still works through LiteLLM with cost ledger and Langfuse
  parity before the Seedream flip.
- `resolve_panel_references()` is the single source of truth for refs used by
  draw and cost estimation.
- Labs can compare prompt A/B variants for one selected model.
- Seedream promotion follows the LiteLLM-first decision ladder and does not
  add app-side direct fal routing unless the LiteLLM options fail.

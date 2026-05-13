# Labs Phase 0+1 Implementation Plan

Date: 2026-05-13

## Status

Ready for implementation.

Design source:
[`docs/superpowers/specs/2026-05-13-labs-phase-0-1-design.md`](../specs/2026-05-13-labs-phase-0-1-design.md)

## Goal

Implement the approved Phase 0+1 design: extract production image generation
behind a provider boundary, make draw-stage references role-aware, add Labs
prompt A/B mode, then validate and promote Seedream V4.5 Edit through the
LiteLLM-first decision ladder.

## Success Criteria

- Existing image generation through LiteLLM keeps the same request shape for
  no-ref and multi-ref calls before the Seedream flip.
- `ai/client.py:generate_image()` is no longer the monolithic HTTP/image
  accounting implementation.
- Draw-stage reference resolution returns ordered `RefImage` objects and is
  shared by draw and cost estimation.
- Labs supports one-model prompt A/B runs and persists variant-specific cells.
- Seedream is validated through LiteLLM built-in routing before any custom
  plugin is added.
- `rtk uv run pytest novel_to_comic/tests/` passes.
- The web build/test command used by the repo passes after the Labs UI change.

## Implementation Sequence

### Slice 1: Provider Types and LiteLLM Extraction

Files:

- `novel_to_comic/src/novel_to_comic/ai/providers/__init__.py`
- `novel_to_comic/src/novel_to_comic/ai/providers/base.py`
- `novel_to_comic/src/novel_to_comic/ai/providers/litellm_http.py`
- `novel_to_comic/src/novel_to_comic/ai/providers/selector.py`
- `novel_to_comic/src/novel_to_comic/ai/client.py`
- `novel_to_comic/tests/test_ai_client.py`

Steps:

1. Add `RefImage`, `ProviderRawResult`, and `ImageProvider`.
2. Move image-only helpers from `ai/client.py` to `litellm_http.py` only when
   they are truly LiteLLM request-shape concerns:
   - `_valid_gpt_image_2_size`
   - `_image_size`
   - `_mime_type`
   - LiteLLM endpoint selection
   - multipart file construction
3. Keep shared helpers in `ai/client.py` temporarily if moving them would
   disturb text generation.
4. Implement `LitellmHttpProvider.generate()`.
5. Implement `selector.pick()` returning `LitellmHttpProvider`.
6. Change `ai/client.generate_image()` to accept `refs: list[RefImage]` and
   call the provider.
7. Update image tests to patch the provider HTTP client at the new import path.

Verification:

```bash
rtk uv run pytest novel_to_comic/tests/test_ai_client.py
```

Expected test focus:

- no-ref image calls still hit `/v1/images/generations`;
- ref image calls still hit `/v1/images/edits`;
- `quality` is still sent when configured;
- `steps` and `response_format` are still omitted;
- image bytes are written to the requested output path.

### Slice 2: Image Finalisation Extraction

Files:

- `novel_to_comic/src/novel_to_comic/ai/finalisation.py`
- `novel_to_comic/src/novel_to_comic/ai/client.py`
- `novel_to_comic/tests/test_ai_client.py`
- `novel_to_comic/tests/test_image_failure_meta.py`

Steps:

1. Move image-call event insert/finalize orchestration to
   `finalisation.py`.
2. Preserve the pre-call `_insert_event` timing before provider execution.
3. Preserve success, refusal, cancellation, and failure behavior.
4. Preserve failed-request billing when `ai_bill_failed_requests` is
   `estimate_all`.
5. Ensure finalisation builds Langfuse input/output payloads equivalent to the
   current code.
6. Keep text call finalisation in `ai/client.py` unless a helper can be moved
   without changing behavior.

Verification:

```bash
rtk uv run pytest novel_to_comic/tests/test_ai_client.py novel_to_comic/tests/test_image_failure_meta.py
```

Expected test focus:

- event insert happens before provider execution;
- event finalize status is correct for success/failure/refusal/cancel;
- usage extraction still reads LiteLLM response headers and hidden response cost;
- billable failed image usage remains governed by config.

### Slice 3: Role-Aware Draw References

Files:

- `novel_to_comic/src/novel_to_comic/stages/s7_draw.py`
- `novel_to_comic/src/novel_to_comic/clients/flux.py`
- `novel_to_comic/tests/test_image_failure_meta.py`
- any stage tests that patch `generate_image_multi_ref`

Steps:

1. Replace `resolve_panel_reference_paths()` with
   `resolve_panel_references() -> list[RefImage]`.
2. Assign roles:
   - character refs: `subject`
   - prop refs identified by path: `prop`
   - previous panel image: `continuity`
   - style sample: `style`
   - location plate: `location_plate`
3. Apply model-specific caps after role assignment:
   - GPT Image 2: current minimal subject behavior, no style/location/continuity;
   - Seedream: first 10 refs in role-priority order;
   - default: all applicable refs in role-priority order.
4. Update `estimate_panel_image_cost_usd()` to use the new function.
5. Update draw execution to pass rich refs into `clients/flux`.
6. Update `clients/flux.generate_image_multi_ref()` to accept `refs` and pass
   them through to `ai.generate_image()`.

Verification:

```bash
rtk uv run pytest novel_to_comic/tests/test_image_failure_meta.py
```

Expected test focus:

- GPT Image 2 still receives minimal refs;
- Seedream receives up to 10 refs;
- default models include subject, continuity, style, and location refs when
  configured;
- cost estimation and draw upload count the same refs.

### Slice 4: Labs Prompt A/B Backend

Files:

- `novel_to_comic/src/novel_to_comic/labs/runner.py`
- `novel_to_comic/src/novel_to_comic/labs/storage.py`
- `novel_to_comic/src/novel_to_comic/server/routers/labs.py`
- `novel_to_comic/tests/test_labs_costs.py`
- new targeted Labs API/storage tests if no existing file fits

Steps:

1. Add `prompt_variant_b` to `LabsPanelSpec`.
2. Add `prompt_compare_mode` to `LabsRunSpec`.
3. Validate comparison mode in `/api/labs/runs`:
   - exactly one model;
   - every panel has non-empty prompt A and prompt B;
   - prompt lengths respect `MAX_PROMPT_LEN`.
4. Make storage cell paths variant-aware. Use `A` for normal-mode cells and
   store variant metadata in every cell JSON.
5. Update manifest writing with `prompt_compare_mode` and both prompts.
6. Update run detail stitching so result rows include panel + variant and use
   variant-specific image URLs.
7. Update cost summing to include variant cells.

Verification:

```bash
rtk uv run pytest novel_to_comic/tests/test_labs_costs.py
```

Add tests that cover:

- normal mode stores one variant per panel;
- comparison mode stores A/B cells separately;
- comparison mode rejects multiple models;
- run detail returns variant-specific prompts and image URLs.

### Slice 5: Labs Prompt A/B Frontend

Files:

- `web/src/api/labs.ts`
- `web/src/pages/LabsRoom.tsx`
- `web/src/api/queries.ts` only if type changes require it
- frontend tests if Labs currently has coverage hooks

Steps:

1. Extend API types for `prompt_variant_b`, `prompt_compare_mode`, and result
   row variants.
2. Add a "Compare two prompts" toggle in the run configuration area.
3. When enabled:
   - reduce selected models to one;
   - disable multi-select behavior in `ModelPicker`;
   - render A/B textareas per panel;
   - send `prompt_compare_mode: true`.
4. Update `ResultsGrid` and `Lightbox` to display variant labels and
   variant-specific prompts.
5. Preserve normal-mode UI behavior.

Verification:

Run the existing web build/test command. If uncertain, inspect `web/package.json`
and run the available build or test script.

Manual UI check:

- start the dev server;
- open `/labs`;
- enable prompt comparison;
- verify model selection locks to one model;
- verify A/B textareas render;
- run one cheap model if credentials are available, or verify payload shape in
  the browser/network layer.

### Slice 6: Full Backend Regression

Run:

```bash
rtk uv run pytest novel_to_comic/tests/
```

Fix regressions before starting Seedream routing. The provider split and Labs
A/B work must be stable before touching production model aliases.

### Slice 7: Seedream Built-In LiteLLM Pre-Flight

Files:

- `litellm/config.yaml` for temporary alias, then final alias if accepted
- `novel_to_comic/src/novel_to_comic/litellm_pricing_overrides.yaml`
- `novel_to_comic/src/novel_to_comic/stages/s7_draw.py`
- optional pre-flight script under `novel_to_comic/scripts/`

Steps:

1. Add a temporary alias:

   ```yaml
   - model_name: image-balanced-seedream-test
     litellm_params:
       model: fal_ai/bytedance/seedream/v4.5/edit
       api_key: os.environ/FAL_KEY
   ```

2. Restart LiteLLM.
3. Send a real `/v1/images/edits` request with at least three refs.
4. Inspect:
   - does the request return an image;
   - do multiple refs affect the output;
   - do cost headers/usage appear;
   - does Langfuse/cost ledger shape remain usable.
5. If the built-in route passes, promote it:
   - change `image-balanced` to Seedream;
   - keep Gemini Pro as `image-balanced-gemini`;
   - add/confirm pricing override at `$0.04/image`;
   - ensure Seedream cap behavior is active for `image-balanced`.

Verification:

- pricing audit passes at server startup;
- a Labs comparison between old Gemini Pro alias and Seedream works;
- a draw-stage balanced run calls Seedream.

### Slice 8: LiteLLM Custom fal Plugin Fallback

Only do this if Slice 7 fails or drops multi-ref conditioning.

Files:

- `litellm_handlers/__init__.py`
- `litellm_handlers/fal_provider.py`
- `docker-compose.yml`
- `litellm/config.yaml`
- `novel_to_comic/scripts/test_fal_proxy.py`

Steps:

1. Port the Labs fal queue client into `FalQueueLLM`.
2. Convert OpenAI-shaped image edit inputs into fal `image_urls` data URIs.
3. Return OpenAI-shaped `b64_json` data.
4. Mount `litellm_handlers` into the LiteLLM container.
5. Add `custom_provider_map`.
6. Point `image-balanced` at the custom provider route.
7. Add and run a smoke script against localhost LiteLLM.

Verification:

- smoke script returns a real image;
- cost ledger and Langfuse shape match existing LiteLLM-routed calls;
- Labs Gemini-vs-Seedream comparison works through the production gateway.

## Risk Controls

- Keep the first provider extraction behavior-preserving and covered by
  request-shape tests.
- Do not modify `litellm/config.yaml` production aliases until after the full
  backend regression passes.
- Do not add `FalNativeProvider` unless both LiteLLM paths are rejected.
- Avoid changing text-generation helpers while extracting image finalisation.
- Keep Labs A/B storage variant-aware from the start to avoid overwritten cells.

## Final Verification Checklist

- `rtk uv run pytest novel_to_comic/tests/`
- Web build/test command passes.
- `/labs` normal mode still runs existing model grids.
- `/labs` prompt A/B mode renders two prompt variants for one selected model.
- Seedream pre-flight decision is recorded in the implementation notes or final
  summary.
- If Seedream is promoted, `image-balanced-gemini` rollback alias exists.

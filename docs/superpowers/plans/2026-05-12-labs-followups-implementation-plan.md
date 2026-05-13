# Labs Follow-ups Implementation Plan

Date: 2026-05-12

## Status

Ready to plan. Labs (`/labs` page, top-level) is shipped and working as an
A/B harness across nine image models. Three follow-up workstreams emerged from
running real experiments; they overlap in code so this plan sequences them.

## Context — what's already built and what we learned

**Labs is live.** Top-level `/labs` page lets a user pick N image models, write
panel prompts (from a fixture or imported from a project), and render a
panels × models grid with cost + latency per cell. Provider clients live in
[`novel_to_comic/labs/providers/`](../../../novel_to_comic/src/novel_to_comic/labs/providers/)
for fal.ai, together.ai, and the existing LiteLLM pipeline. Curated registry at
[`novel_to_comic/labs/labs_models.yaml`](../../../novel_to_comic/src/novel_to_comic/labs/labs_models.yaml).

**Three observations from real runs drive this plan:**

1. **Panel prompts are weak.** The Labs fixture uses hand-written prose like
   _"Mid-shot inside the tavern. Anya stands at left, half-turned toward Rurik
   who leans across the bar at right"_ and gets noticeably better images than
   the pipeline's assembled prompts (`Composition: mid-shot. Setting: tavern.
   Lighting: lantern…`). Same model, very different output quality.
2. **LiteLLM is leaking quality from Nano Banana 2.** Calling
   `fal-ai/nano-banana-2/edit` directly through Labs produces materially better
   images than `image-fast` through the LiteLLM proxy, even though both end up
   at the same underlying Gemini 3.1 flash image model. The OpenAI
   `/v1/images/edits` shape strips role information from references.
3. **Seedream V4.5 Edit is the best balanced-tier model we tested.** Strong
   character consistency, ~$0.04/image, 60s latency, supports up to 10
   reference images. Worth promoting to production `image-balanced`, but it's
   on fal — we need to keep it inside our centralised tracking story.

## Goal

Land the three observations as production changes without three separate
refactors of `ai/client.py`. Build a small provider abstraction once, then plug
each workstream into it.

## Sequencing

```
Phase 0: Foundation ──► Phase 1: Seedream ──┐
                     └► Phase 2: Prompts ───┴──► Phase 3: Native Gemini
```

After Phase 0 lands, Phases 1 and 2 can run in parallel (different parts of the
stack). Phase 3 should wait until at least one of 1 or 2 is shipped so we have
a stable baseline to A/B against.

| Phase | Scope | Why this order | Est. size |
|---|---|---|---|
| 0 | Provider abstraction + finalisation extraction + Labs prompt A/B | Unblocks 1, 2, 3. Doing it once explicitly is cheaper than three competing refactors. | 1 PR, ~600 LOC moved |
| 1 | Seedream V4.5 Edit as new `image-balanced`, **routed through LiteLLM by default** | Smallest concrete win. Decision ladder: built-in `fal_ai/*` → custom LiteLLM plugin → direct provider. Most likely outcome is a LiteLLM plugin (Option B). | ~5 files (Option A) or ~7 files (Option B) |
| 2 | Better panel prose | Re-evaluate prompts against the model the pipeline will actually use (Seedream after Phase 1). | 3–8 files depending on chosen intervention |
| 3 | Native Gemini path via `google-genai` | Biggest yak shave (new SDK + auth). Lower priority once Seedream is the balanced tier. Investigate LiteLLM passthrough/plugin alternatives before going direct. | ~4 files |

**Centralisation principle.** All three phases prefer keeping calls inside
LiteLLM (config-driven aliases, one cost-tracking pipeline, one Langfuse
hook). The Phase 0 abstraction is the escape hatch for cases where LiteLLM
can't represent the underlying API faithfully (lossy translation, missing
provider features, multimodal inputs the OpenAI shape can't carry). Reach
for the direct-provider path only after the LiteLLM-native and
LiteLLM-plugin options have been verified to fall short.

---

## Phase 0 — Foundation

**Goal:** Refactor today's monolithic `ai/client.py:generate_image()` into a
pluggable provider system, and extend Labs to A/B prompt variants. **No
behaviour change for users.**

### What exists today

- [`ai/client.py:818`](../../../novel_to_comic/src/novel_to_comic/ai/client.py)
  — `generate_image()` is one HTTP function tightly coupled to LiteLLM's
  `/v1/images/generations` and `/v1/images/edits` endpoints. Cost/Langfuse
  finalisation is interleaved with the HTTP call inside the same function.
- [`clients/flux.py`](../../../novel_to_comic/src/novel_to_comic/clients/flux.py)
  — facade that all stage code calls. Dispatches to `ai_generate_image`.
- [`s7_draw.py:resolve_panel_reference_paths`](../../../novel_to_comic/src/novel_to_comic/stages/s7_draw.py)
  — emits two flat lists: `subject_refs` and `style_refs`. Loses per-ref role
  semantics that downstream providers (especially Gemini/fal native) could
  use.
- Labs already has a working provider abstraction at
  [`labs/providers/base.py`](../../../novel_to_comic/src/novel_to_comic/labs/providers/base.py)
  — but it's labs-only and doesn't do cost finalisation or Langfuse. Use it
  as the shape inspiration, not a port.

### Deliverables

1. **New package `novel_to_comic/ai/providers/`:**
   - `base.py` — `ImageProvider` protocol:
     ```
     class ImageProvider(Protocol):
         name: str
         async def generate(
             self, *,
             model_alias: str,
             prompt: str,
             refs: list[RefImage],
             width: int, height: int,
             params: dict[str, Any] | None,
             config: Config,
         ) -> ProviderRawResult: ...
     ```
   - `RefImage` dataclass:
     `path: Path, role: Literal["subject", "style", "continuity", "location_plate", "prop"]`
   - `ProviderRawResult` dataclass: `image_bytes, mime, latency_ms,
     provider_request_id, raw_response, provider_cost_usd (optional)`.
   - `litellm_http.py` — extract the existing `generate_image` body. Implements
     `ImageProvider`. **Byte-for-byte equivalent request to today's call.**
   - `selector.py` — `pick(model_alias, config) -> ImageProvider`. Today:
     always returns `LitellmHttpProvider`. Single place to grow in later
     phases. **Note**: the goal is for `selector` to stay mostly trivial —
     Phases 1 and 3 each evaluate whether their provider can live inside
     LiteLLM (custom plugin) before adding a new branch here. If the
     LiteLLM-plugin path works, the selector keeps routing everything to
     `LitellmHttpProvider` and the per-provider knowledge lives in the
     proxy, not in our code.
2. **Extract finalisation** into `novel_to_comic/ai/finalisation.py`:
   - `async def finalise_image_call(...)` — handles `_insert_event`,
     `_finalize_event`, cost estimation, error capture, ApiResult assembly.
   - `generate_image()` in `ai/client.py` becomes a thin wrapper:
     `provider = selector.pick(model); raw = await provider.generate(...);
     return await finalise_image_call(raw, ...)`.
3. **Refactor `resolve_panel_reference_paths`** to return `list[RefImage]`
   with explicit roles instead of two flat lists. Update
   `clients/flux.py:generate_image_multi_ref` to pass them through. The
   LiteLLM provider flattens roles back to OpenAI's anonymous `image[]`
   multipart for now — Phases 2 and 3 will exploit the roles.
4. **Labs prompt A/B mode:**
   - Extend `LabsRunSpec` with optional per-panel `prompt_variant_b: str |
     None`. When present, the runner emits an additional cell row in the
     grid (same model, "variant B" label) for that panel.
   - Frontend: in `LabsRoom.tsx`, add a "Compare two prompts" toggle next to
     the model picker. When on, the panel editor shows two textareas (A/B)
     per panel and locks the model picker to a single selection.
   - Results grid: when A/B mode, rows are `panel × variant` instead of just
     `panel`.

### Files touched

- New: `novel_to_comic/src/novel_to_comic/ai/providers/{__init__,base,litellm_http,selector}.py`
- New: `novel_to_comic/src/novel_to_comic/ai/finalisation.py`
- Edited: `novel_to_comic/src/novel_to_comic/ai/client.py` (shrink `generate_image`)
- Edited: `novel_to_comic/src/novel_to_comic/clients/flux.py`
- Edited: `novel_to_comic/src/novel_to_comic/stages/s7_draw.py` (ref resolution)
- Edited: `novel_to_comic/src/novel_to_comic/labs/runner.py` (prompt variant)
- Edited: `novel_to_comic/src/novel_to_comic/labs/storage.py` (variant in manifest)
- Edited: `novel_to_comic/src/novel_to_comic/server/routers/labs.py` (variant in payload)
- Edited: `web/src/api/labs.ts` + `web/src/pages/LabsRoom.tsx` (A/B toggle, two-textarea editor, variant column in grid)

### Exit criteria

- All existing tests in [`novel_to_comic/tests/`](../../../novel_to_comic/tests/) pass unchanged.
- A draw-stage run on a real project produces byte-comparable cost ledger
  entries and Langfuse traces vs. the pre-refactor baseline.
- Labs prompt A/B mode renders two variants of one panel correctly on a
  fast/cheap model (use `nano-banana-2-edit`).
- `clients/flux.py` no longer references `ai_generate_image` directly — it
  goes through `selector` + `finalise_image_call`.

### Risks / open questions

- **Cost estimation timing.** Today's `_insert_event` runs before the
  provider call to record an estimate; `_finalize_event` runs after. The
  finalisation module needs to expose both halves cleanly without leaking
  state across providers.
- **Image-edit vs. image-generation endpoint dispatch.** Currently lives
  inside `generate_image()` (`if ref_data: endpoint = "/v1/images/edits"`).
  This is a LiteLLM-shape concern; it should live entirely inside
  `litellm_http.py`, not in the protocol.
- **What does `params` look like across providers?** Keep it provider-opaque
  in the protocol — `selector` adds provider-specific param defaults from
  config when picking. Don't try to unify provider params at the protocol
  level.

### Pickup prompt (for a fresh session)

> Read this plan's Phase 0 section. Read
> `novel_to_comic/src/novel_to_comic/ai/client.py:818-1000`,
> `novel_to_comic/src/novel_to_comic/clients/flux.py`,
> `novel_to_comic/src/novel_to_comic/stages/s7_draw.py:170-220`, and
> `novel_to_comic/src/novel_to_comic/labs/providers/base.py`. Then implement
> the deliverables in order: (1) provider package + protocol, (2)
> finalisation extraction, (3) ref-role refactor, (4) Labs prompt A/B.
> Constraint: no behaviour change for the existing pipeline — verify by
> running `uv run pytest tests/` and one real draw-stage call before/after.

---

## Phase 1 — Seedream V4.5 Edit as production `image-balanced`

**Goal:** Promote Seedream to the production balanced tier while keeping all
model calls flowing through one central interface (LiteLLM proxy preferred)
with cost tracking and Langfuse traces intact.

### What we already have

- [`novel_to_comic/labs/providers/fal.py`](../../../novel_to_comic/src/novel_to_comic/labs/providers/fal.py)
  — working fal.ai client using the queue API with data-URI references. The
  status_url/response_url bug from the first Labs run is already fixed.
- Pricing data: ~$0.04/image, 60s typical latency, up to 10 reference
  images, supports multi-image conditioning natively.

### Decision ladder — pick the simplest option that works

The "centralised tracking" goal is best satisfied by keeping the call inside
LiteLLM. Three integration shapes, in increasing order of effort. **Stop at
the first one that passes the pre-flight test.**

#### Option A — LiteLLM's built-in `fal_ai/*` provider (1 hour to verify)

LiteLLM ships with image-generation support for `fal_ai/*` models. The
proxy receives an OpenAI-shaped image-edit request, translates it to fal's
API, returns an OpenAI-shaped response. Cost + Langfuse hooks fire normally.

**Pre-flight test before implementing anything:**

```bash
# 1. Add a temporary alias to litellm/config.yaml
- model_name: image-balanced-seedream-test
  litellm_params:
    model: fal_ai/bytedance/seedream/v4.5/edit
    api_key: os.environ/FAL_KEY

# 2. Restart the LiteLLM container
docker compose restart litellm

# 3. Hit it with a multi-ref image-edit request
curl -X POST http://localhost:4000/v1/images/edits \
  -H "Authorization: Bearer $LITELLM_MASTER_KEY" \
  -F "model=image-balanced-seedream-test" \
  -F "prompt=anya at the bar, lantern light, painterly comic" \
  -F "image=@char_anya.png" \
  -F "image=@char_rurik.png" \
  -F "image=@loc_tavern.png" \
  -F "size=1024x1024" \
  -o out.png

# 4. Inspect the response: did it return an image, or an error? If image:
#    open it and check whether all three refs influenced the output (subject
#    identity, location grounding). If only the first ref was honoured,
#    multi-ref didn't make it through.
```

Three possible outcomes:

- **Image returned and multi-ref clearly honoured**: ship Option A. Skip
  options B and C entirely. Phase 1 collapses to one config edit + one
  pricing override.
- **Image returned but multi-ref dropped (only first ref affected output)**:
  Option A is usable for text-to-image fal models (Recraft V4, FLUX
  schnell) but useless for Seedream's multi-ref strength. Move to Option B.
- **400/422 error from LiteLLM or fal**: translation layer doesn't
  understand the shape. Move to Option B.

Realistic expectation: outcome 2 or 3. The OpenAI image-edit API is
anonymous-files-only — LiteLLM's translator can't invent ref-role
semantics that don't exist in the source shape.

#### Option B — LiteLLM custom provider plugin (1–2 days)

LiteLLM exposes a `CustomLLM` Python plugin interface. Write a class that
translates between OpenAI-shaped requests and fal's native queue API. The
plugin lives in a file mounted into the LiteLLM container; cost tracking
and Langfuse callbacks fire because the proxy still owns the request.

**Sketch:**

```python
# litellm_handlers/fal_provider.py — new file, mounted into LiteLLM container
import base64, mimetypes, os
from litellm import CustomLLM
import httpx

FAL_QUEUE = "https://queue.fal.run"

class FalQueueLLM(CustomLLM):
    """Custom LiteLLM provider for fal.ai queue-API image endpoints."""

    def image_generation(self, model: str, prompt: str, **kwargs) -> dict:
        # kwargs carries: image (list[bytes] or list[file-like]), size, n, ...
        endpoint = model.removeprefix("fal-queue/")
        refs = self._collect_refs(kwargs)
        payload = self._build_payload(endpoint, prompt, refs, kwargs)
        request_id, status_url, response_url = self._submit(endpoint, payload)
        self._poll(status_url, request_id)
        result = self._fetch(response_url)
        image_url = result["images"][0]["url"]
        image_bytes = httpx.get(image_url).content
        b64 = base64.b64encode(image_bytes).decode()
        # Return OpenAI-shaped response so LiteLLM's cost/usage hooks fire
        return {"data": [{"b64_json": b64}], "model": model}

    def _collect_refs(self, kwargs) -> list[str]:
        # Convert multipart `image[]` files → data URIs
        ...

    def _build_payload(self, endpoint, prompt, refs, kwargs):
        # Mirror labs/providers/fal.py:_build_payload
        ...

    # _submit / _poll / _fetch reuse the same queue-API flow as
    # labs/providers/fal.py — port verbatim.
```

**Wire it into LiteLLM:**

```yaml
# litellm/config.yaml
litellm_settings:
  custom_provider_map:
    - {"provider": "fal-queue", "custom_handler": "fal_provider.FalQueueLLM"}

model_list:
  - model_name: image-balanced
    litellm_params:
      model: fal-queue/bytedance/seedream/v4.5/edit
      api_key: os.environ/FAL_KEY
```

**Volume mount in `docker-compose.yml`:**

```yaml
litellm:
  volumes:
    - ./litellm/config.yaml:/app/config.yaml
    - ./litellm_handlers:/app/litellm_handlers  # new
  environment:
    PYTHONPATH: /app:/app/litellm_handlers
```

#### Option C — Direct fal provider in `ai/providers/fal_native.py` (fallback)

Only reach for this if Option B's operational complexity is unacceptable
(maintaining a plugin across LiteLLM upgrades, two-codebase debugging).
This is the original Phase 1 plan: a `FalNativeProvider` in our repo,
bypassing LiteLLM, calling fal directly, with cost + Langfuse handled by
Phase 0's `finalise_image_call`. Same quality result as Option B but
"centralised tracking" lives in our Python code rather than the proxy.

### Deliverables — Option A path (best case)

1. Add `image-balanced` alias pointing at `fal_ai/bytedance/seedream/v4.5/edit`
   in [`litellm/config.yaml`](../../../litellm/config.yaml). Keep the old
   Gemini Pro alias as `image-balanced-gemini` so rollback is one edit.
2. Pricing override entry in
   [`litellm_pricing_overrides.yaml`](../../../novel_to_comic/src/novel_to_comic/litellm_pricing_overrides.yaml)
   at $0.04/image. Verify [`audit_pricing`](../../../novel_to_comic/src/novel_to_comic/usage.py)
   passes at startup.
3. Per-model ref caps in
   [`s7_draw.py`](../../../novel_to_comic/src/novel_to_comic/stages/s7_draw.py).
   Generalise `_gpt_image_2_subject_refs` into a model-keyed dispatch:
   - gpt-image-2: current behaviour (one front-facing per character).
   - seedream: up to 10 refs, subject-first ordering.
   - default: pass all.
4. Bump `CANARY_GENERATION_JOB_TIMEOUT_SECONDS` if 60s × concurrent panels
   exceeds the current 900s default.

### Deliverables — Option B path (custom provider plugin)

1. New directory `litellm_handlers/` at repo root with `__init__.py` and
   `fal_provider.py` (the `FalQueueLLM` class sketched above).
2. `docker-compose.yml` mount + `PYTHONPATH` update so the LiteLLM container
   loads the plugin.
3. `custom_provider_map` entry + new `image-balanced` alias in
   [`litellm/config.yaml`](../../../litellm/config.yaml).
4. Same pricing override + ref caps as Option A.
5. Integration test: a Python script under
   `novel_to_comic/scripts/test_fal_proxy.py` that hits the proxy and
   verifies a real Seedream image comes back. Run as part of pre-deploy
   checks.

### Deliverables — Option C path (direct provider, fallback)

Original five-deliverable list:

1. `novel_to_comic/ai/providers/fal_native.py` implementing `ImageProvider`.
   Port `labs/providers/fal.py`, honour `RefImage.role` (subject refs
   first), return `ProviderRawResult` with `provider_cost_usd=None`.
2. Pricing override entry (same as Options A/B).
3. Selector wiring: `selector.pick()` routes `fal-ai/*` models to
   `FalNativeProvider`.
4. Config flag `Config.image_balanced_provider: "gemini" | "seedream"`.
5. Per-model ref caps (same as Options A/B).

### Validation (all options)

- Labs A/B between current `image-balanced` (Gemini Pro) and the new
  Seedream path on 2–3 real project scenes (8 panels each, 2–3 characters).
- Compare: character identity drift, scene grounding, anatomy correctness,
  cost per panel.
- Ship when ≥6/8 panels rated equal or better by the user.
- For Option B specifically: verify cost ledger entries and Langfuse
  traces appear identical in shape to existing LiteLLM-routed calls.

### Exit criteria

- Production draw run with `quality_preset: balanced` calls Seedream and
  produces images with full cost-tracking + Langfuse parity.
- A regression run with the alias pointing back at Gemini produces
  byte-identical behaviour to today.
- Pricing audit passes at server startup.

### Risks / open questions

- **60s latency × 50 panels = 50 minute draw stages.** Check
  `CANARY_GENERATION_JOB_TIMEOUT_SECONDS` (default 900s = 15min, set in
  [`server/app.py`](../../../novel_to_comic/src/novel_to_comic/server/app.py)).
  Bump if needed.
- **Option A multi-ref support is uncertain.** Pre-flight resolves this in
  one hour — don't skip it.
- **Option B LiteLLM upgrade fragility.** LiteLLM's `CustomLLM` API has
  stabilised but not frozen. Pin the LiteLLM version in
  `docker-compose.yml` and only upgrade after re-testing the plugin.
- **Cost-source attribution.** fal doesn't return cost; the pricing table
  supplies it. Today `usage.py` distinguishes provider-reported vs.
  estimated cost. Add `cost_source: "pricing_table"` so the ledger UI is
  honest about where the number came from. Applies to all three options.
- **Plugin testability.** Option B's plugin code can't be tested by the
  Canary pytest suite — it runs inside LiteLLM. Plan integration tests via
  the proxy (a smoke-test script that hits localhost:4000).

### Pickup prompt

> Read this plan's Phase 1 section. Verify Phase 0 is merged (check that
> `novel_to_comic/ai/providers/` exists). Start with Option A's pre-flight
> `curl` test — that's a 1-hour check that may collapse Phase 1 to one
> config edit. If multi-ref doesn't make it through LiteLLM's `fal_ai/*`
> translator, build Option B (the custom provider plugin). Reach Option C
> only if Option B's operational cost is unacceptable. Validate via Labs
> A/B before flipping the `image-balanced` alias.

---

## Phase 2 — Better panel prose

**Goal:** Bring production panel prompts up to the quality of the Labs
fixture's hand-written prose.

### What exists today

- [`prompting.py:417`](../../../novel_to_comic/src/novel_to_comic/prompting.py)
  — `build_planned_panel_prompt_spec()` builds an `ImagePrompt` from a
  `PlannedPanel`, walking character anchors, composition, setting, lighting,
  mood, key objects, props, constraints.
- [`prompting.py:579`](../../../novel_to_comic/src/novel_to_comic/prompting.py)
  — `_render_panel_prompt_body_parts()` is the renderer that produces the
  current labelled output: `Composition: …. Setting: …. Lighting: ….`.
  **This is the function the prose pass either replaces or augments.**
- [`server/routers/stages.py:234`](../../../novel_to_comic/src/novel_to_comic/server/routers/stages.py)
  and
  [`prompt_instructions.py:152`](../../../novel_to_comic/src/novel_to_comic/prompt_instructions.py)
  — re-render hooks called when a user edits a panel via the Direct room.
  Whichever intervention ships, these need updating too.

### Three candidate interventions

Pick one in a 1-page decision artifact using Labs prompt A/B mode (built in
Phase 0). Run the same panel through (a), (b), and the current renderer on
the production model (Seedream after Phase 1). Decide based on results:

- **(a) Renderer rewrite.** Rewrite `_render_panel_prompt_body_parts` to
  emit prose. Deterministic, no per-panel inference cost, but limited by
  what's already in `PlannedPanel`. Best if our structured fields are
  actually rich enough and the only issue is presentation.
- **(b) LLM prose pass.** New stage helper between `direct` and `draw` that
  takes the structured `ImagePrompt` and rewrites it to prose using a small
  model (panel-fast tier, ~$0.001/panel). Highest ceiling. Adds a stage call
  and a new failure mode.
- **(c) Storyboard-schema change.** Have the LLM that produces
  `PlannedPanel` write a prose `panel_description` field directly. Most
  upstream — touches storyboard prompt templates and the `PlannedPanel`
  model. Best long-term but biggest blast radius. Defer unless (a) and (b)
  both fall short.

### Deliverables (assuming intervention (b) — adjust if you pick differently)

1. **New `ImagePrompt.prose_prompt: str | None`** field on the
   [`ImagePrompt`](../../../novel_to_comic/src/novel_to_comic/models/prompt.py)
   model. `full_prompt` stays as fallback for backward compatibility.
2. **Bump `IMAGE_PROMPT_VERSION`** in
   [`prompting.py`](../../../novel_to_comic/src/novel_to_comic/prompting.py)
   so existing projects regenerate prose on next draw run.
3. **New prose generator** in `prompting.py`:
   - `async def generate_prose_prompt(config, prompt: ImagePrompt) -> str`
   - Uses `prompt-fast` gateway alias.
   - Takes the structured fields + character `visual_anchor`s **verbatim**
     (AGENTS.md rule: never paraphrase anchors).
   - System prompt: "Rewrite as a single paragraph in the style of a comic
     panel direction. Preserve all character names and visual anchors
     exactly. Don't drop any constraint."
4. **Wire into `direct` stage** so prose is generated alongside the
   structured prompt, cached in the panel JSON, regenerated when the user
   edits a panel.
5. **`clients/flux.py` prefers `prose_prompt` when present**, falls back to
   `full_prompt`.
6. **Cost estimation update** in
   [`credits.py`](../../../novel_to_comic/src/novel_to_comic/server/credits.py)
   to include one prompt-fast call per panel in the `direct` stage estimate.

### Validation

- Labs prompt A/B mode on 2 real scenes (8 panels each). One column =
  current structured prompt, other = generated prose.
- Both run against Seedream (or whatever model is the current balanced
  tier).
- Ship when ≥80% of panels are rated equal or better with prose.
- Spot-check: confirm all character `visual_anchor` strings appear verbatim
  in the prose. A unit test on the generator output should enforce this.

### Exit criteria

- A fresh project run with `quality_preset: balanced` produces prose
  prompts visible in the Direct room panel editor.
- Editing a panel re-runs the prose generator (existing edit hook fires).
- Existing tests pass; new test asserts `visual_anchor` verbatim
  preservation in generator output.

### Risks / open questions

- **Anchor preservation under LLM rewrite is the failure mode.** Prompt
  template must be unambiguous; consider a post-validation step that
  rejects prose missing any anchor and falls back to structured.
- **Cost transparency.** Adding ~$0.001/panel to a 50-panel scene is $0.05
  — peanuts, but it should show up in the cost estimate UI for trust.
- **Storyboard-schema change (intervention (c)) is still the right
  long-term answer.** Plan a follow-up to migrate once (b) is shipped and
  we know what the ideal prose looks like.

### Pickup prompt

> Read this plan's Phase 2 section. Read `prompting.py:417-680` and the
> Labs fixture at
> `novel_to_comic/src/novel_to_comic/labs/fixtures/sample_scene.json` to
> ground on the prose target. Run a Labs prompt A/B on a real scene to
> confirm the quality gap exists in production data. Write the 1-page
> decision artifact comparing interventions (a)/(b)/(c). Implement the
> chosen one. Validate via Labs A/B at ≥80% win rate before shipping.

---

## Phase 3 — Native Gemini path

**Goal:** Reclaim the quality currently lost by routing Gemini 3 image
models through LiteLLM's OpenAI-compatible image-edit shape.

### What exists today

- `image-fast` / `image-balanced` (pre-Phase 1) /
  [`litellm/config.yaml`](../../../litellm/config.yaml) route to
  `vertex_ai/gemini-3.1-flash-image-preview` and
  `vertex_ai/gemini-3-pro-image-preview` through LiteLLM.
- LiteLLM translates the call to OpenAI's `/v1/images/edits` shape, which
  flattens reference roles into anonymous `image[]` files and collapses
  arbitrary sizes to one of three OpenAI sizes (see
  [`ai/client.py:1017`](../../../novel_to_comic/src/novel_to_comic/ai/client.py)).
- Vertex credentials already configured at
  [`litellm/gcp-credentials.json`](../../../litellm/gcp-credentials.json).
- Labs has `gemini-3-flash-current` / `gemini-3-pro-current` registered for
  baseline comparison.

### Investigation step (do first)

Two questions to answer in this order — they decide whether Phase 3 is a
LiteLLM-plugin job or a direct-provider job.

**Question 1: where is the quality lost?**

In Labs, compare four paths for the same panel with the same refs:
- `fal-ai/nano-banana-2/edit` (already working)
- `image-fast` via LiteLLM (already working)
- A throwaway native Vertex call using `google-genai` SDK (write a
  one-shot script in `scripts/`)
- *(optional, only if Phase 1 picked Option B)* the same fal route through
  the LiteLLM custom-provider plugin from Phase 1

If native Vertex matches fal: it's a LiteLLM translation bug → either fix
it inside LiteLLM (Question 2) or build a direct native provider in our
code. If native Vertex still trails fal: route Gemini models through fal
permanently; the answer to Question 2 also applies.

**Question 2: can the better path live inside LiteLLM?**

Same ladder as Phase 1 — exhaust the LiteLLM-resident options before
adding a new direct provider:

- **(a) LiteLLM passthrough endpoint** for Vertex. LiteLLM has a
  `/vertex_ai/*` passthrough that forwards verbatim to the Vertex API. If
  the native Vertex call works, route through the passthrough so auth is
  centralised. **Cost tracking is lost** with passthrough — same caveat as
  Phase 1's Option B passthrough. Probably unacceptable.
- **(b) LiteLLM custom provider plugin for Vertex multimodal.** Mirror the
  Phase 1 pattern: a Python plugin in `litellm_handlers/` that translates
  an OpenAI-shaped image request into a native `google-genai` Vertex call,
  returns an OpenAI-shaped response so LiteLLM's cost/Langfuse hooks fire.
  Preserves "everything goes through LiteLLM" without sacrificing native
  Gemini features.
- **(c) Direct provider in `ai/providers/gemini_native.py`.** Original
  Phase 3 plan. Fall back here only if the plugin path is operationally
  unacceptable.

If Phase 1 shipped Option B (LiteLLM custom provider plugin), reuse the
`litellm_handlers/` plumbing (volume mount, custom_provider_map config)
for the Vertex plugin — incremental cost is just the new Python class.

### Deliverables — Option B path (LiteLLM Vertex plugin, preferred)

1. New `litellm_handlers/vertex_multimodal.py` — `VertexMultimodalLLM`
   subclass of `CustomLLM` that uses `google-genai` Vertex client.
   Translates `image[]` multipart + `prompt` → multimodal `Content` parts
   ordered by ref-role hints (subject first via `metadata` field on the
   request). Returns OpenAI-shaped response with native usage block
   surfaced for cost tracking.
2. `custom_provider_map` entry + new aliases in
   [`litellm/config.yaml`](../../../litellm/config.yaml):
   - `image-fast` points at `vertex-multimodal/gemini-3.1-flash-image-preview`
   - `image-quality-gemini` (optional, opt-in alias) points at
     `vertex-multimodal/gemini-3-pro-image-preview`
3. Pricing overrides in
   [`litellm_pricing_overrides.yaml`](../../../novel_to_comic/src/novel_to_comic/litellm_pricing_overrides.yaml)
   for Vertex Gemini image models.
4. **No changes** to `selector.py` — `image-fast` continues routing to
   `LitellmHttpProvider`, which now talks to a smarter LiteLLM.

### Deliverables — Option C path (direct provider, fallback)

1. **Add `google-genai` dependency** to
   [`pyproject.toml`](../../../novel_to_comic/pyproject.toml).
2. **`novel_to_comic/ai/providers/gemini_native.py`** implementing
   `ImageProvider`. Uses `google-genai` Vertex client. Builds multimodal
   contents with refs ordered by `RefImage.role` (subject first, then
   continuity, then style). Returns native usage block for cost mapping.
3. **Selector wiring:**
   - `image-fast`, `image-balanced-gemini` (new alias for fallback /
     opt-in) route to `GeminiNativeProvider`.
   - Existing `image-balanced` alias respects the Phase 1 config flag
     (`gemini` or `seedream`).
4. **Cost mapping** in
   [`model_costs.py`](../../../novel_to_comic/src/novel_to_comic/model_costs.py)
   — Vertex Gemini image models bill differently from OpenAI. Add a
   pricing entry per native call type.
5. **Langfuse parity.** The `finalise_image_call` from Phase 0 should
   already handle this; verify traces appear identical to the LiteLLM path
   for downstream dashboards.

### Validation

- Labs A/B: native Gemini vs LiteLLM/Gemini vs fal/nano-banana-2 on one
  scene. Pick the winner; route `image-fast` accordingly.
- Verify cost ledger and Langfuse traces are present for native calls.
- Verify Vertex billing matches our recorded cost within 5%.

### Exit criteria

- `image-fast` calls hit the native provider when the feature flag is on.
- One full draw run on a real project at `quality_preset: fast` produces
  visibly better images than today's LiteLLM path.
- All tests pass; pricing audit at startup passes.

### Risks / open questions

- **Vertex auth in the plugin path.** If Option B ships, the Vertex
  credentials need to be reachable from inside the LiteLLM container, not
  just from Canary. Easiest: mount
  [`litellm/gcp-credentials.json`](../../../litellm/gcp-credentials.json)
  and set `GOOGLE_APPLICATION_CREDENTIALS` in the LiteLLM container's env.
- **Plugin reuse across Phases 1 and 3.** If both phases ship as LiteLLM
  custom plugins, share the `litellm_handlers/` scaffolding (volume mount,
  config wiring, smoke-test script). Same fragility risk: pin LiteLLM
  version, re-verify on upgrade.
- **Pricing audit failure** if Vertex Gemini image pricing isn't in
  LiteLLM's cost map. Needs a manual override entry regardless of which
  option ships.
- **Provider concurrency.** Vertex enforces project-level quotas. Today
  LiteLLM handles backoff transparently; both plugin and direct paths
  must preserve that (see `_post_with_retry` in `ai/client.py` for the
  pattern).

### Pickup prompt

> Read this plan's Phase 3 section. Verify Phase 0 is merged and check
> what Phase 1 shipped (Option A/B/C — affects whether the
> `litellm_handlers/` plumbing already exists you can reuse). Run the
> investigation: write a one-shot Vertex script, A/B in Labs against
> LiteLLM/Gemini and fal/nano-banana-2. Then walk the Option ladder: try
> the LiteLLM Vertex plugin (Option B) first since it preserves
> centralisation; fall back to a direct `GeminiNativeProvider` (Option C)
> only if the plugin path is operationally unacceptable. Validate cost +
> Langfuse + image quality before flipping the default.

---

## Cross-phase concerns

### Backward compatibility

- `IMAGE_PROMPT_VERSION` bump in Phase 2 forces regeneration of older
  prompts. This is acceptable per AGENTS.md ("breaking JSON/model changes
  are acceptable for now; do not add legacy shims unless explicitly
  requested").
- Phase 0's refactor is byte-equivalent — no version bumps, no schema
  changes, no shims.
- Phase 1 and Phase 3 add config flags rather than changing defaults
  immediately. Roll forward in one config edit, roll back in one config
  edit.

### Cost ledger continuity

- Phase 0's `finalise_image_call` is the single chokepoint for usage
  recording. Every provider funnels through it.
- Phases 1 and 3 add new pricing-table entries in
  `litellm_pricing_overrides.yaml`. `audit_pricing()` at server startup is
  the safety net — startup fails in production if pricing is missing.
- Use `cost_source` field on usage rows to distinguish provider-reported,
  estimated, and pricing-table costs so the ledger UI can be honest.

### Labs as the validation harness

- Every phase uses Labs to A/B before shipping. The harness already
  supports model A/B; Phase 0 adds prompt A/B. Don't ship anything to
  production until it's won in Labs.
- Keep representative Labs runs around (don't auto-delete) so you can refer
  back to the comparison when reviewing the change in PR.

### Testing baseline

Re-run before each phase ships, expecting clean output:

```
cd novel_to_comic && uv run pytest tests/ -x -q
cd novel_to_comic && uv run ruff check src/
cd web && npx tsc --noEmit && npx eslint src/
cd web && npm test -- --run
```

## Open product questions for the user

1. **Phase 1 default**: ship Seedream as `image-balanced` default once it
   wins in Labs, or keep it opt-in for the first month with a config flag?
2. **Phase 2 intervention**: are you OK with the +$0.001/panel cost of the
   LLM prose pass for the typical 50-panel scene? If not, lean toward (a)
   renderer rewrite.
3. **Phase 3 priority**: if Seedream takes over the balanced tier (Phase
   1), `image-fast` (Gemini Flash) and `image-quality` (gpt-image-2) are
   the remaining LiteLLM-routed image models. Is Gemini Flash still your
   draft tier in 6 months, or is `flux-1-schnell` via together (or
   Seedream itself at fast preset) a viable replacement that lets us
   delete the LiteLLM image path entirely?

## Appendix — file map cheat sheet

For fresh agents picking up any phase. All paths repo-relative.

**Backend image generation core:**
- `novel_to_comic/src/novel_to_comic/ai/client.py` — current monolithic
  generator, Phase 0 splits it apart
- `novel_to_comic/src/novel_to_comic/clients/flux.py` — facade all stages
  call
- `novel_to_comic/src/novel_to_comic/config.py` — model aliases, quality
  presets

**Stage code that invokes image generation:**
- `novel_to_comic/src/novel_to_comic/stages/s7_draw.py` — main consumer
- `novel_to_comic/src/novel_to_comic/stages/s2_style.py` — style samples
- `novel_to_comic/src/novel_to_comic/prompting.py` — prompt assembly
  (Phase 2's target)

**Cost / observability:**
- `novel_to_comic/src/novel_to_comic/usage.py` — `audit_pricing`,
  `UsageRecord`
- `novel_to_comic/src/novel_to_comic/model_costs.py` — cost table
- `novel_to_comic/src/novel_to_comic/litellm_pricing_overrides.yaml` —
  manual overrides

**LiteLLM proxy config:**
- `litellm/config.yaml` — alias definitions

**Labs (already shipped):**
- `novel_to_comic/src/novel_to_comic/labs/` — providers, registry,
  runner, storage, fixtures
- `novel_to_comic/src/novel_to_comic/server/routers/labs.py` — `/api/labs`
  endpoints
- `web/src/api/labs.ts` + `web/src/pages/LabsRoom.tsx` — frontend

**Tests:**
- `novel_to_comic/tests/` — backend
- `web/src/__tests__/` — frontend

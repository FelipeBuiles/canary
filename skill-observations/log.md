# Skill Observation Log

Observations captured during task-oriented work. Each entry identifies a
potential skill improvement or new skill opportunity.

**Status key:** OPEN = not yet actioned | ACTIONED = skill updated/created |
DECLINED = user decided not to pursue

---
### Observation 1: Validate gateway cost separately from image success

**Date:** 2026-05-13
**Session context:** Implemented a LiteLLM custom provider for native Vertex Gemini image generation and compared it against current LiteLLM/Gemini plus fal Nano Banana.
**Skill:** New skill candidate: model-provider-evaluation
**Type:** internal
**Phase/Area:** AI gateway/provider rollout validation

**Issue:** A custom LiteLLM provider could successfully return high-quality images while LiteLLM's response-cost header underreported the real image cost by roughly two orders of magnitude. Image success alone was not enough; cost parity had to be validated as its own gate before considering a default flip.

**Suggested improvement:** Create a provider-evaluation workflow skill that requires four independent checks for model routing changes: direct/native smoke call, gateway/proxy smoke call, Labs image comparison on the same prompt and refs, and explicit cost/Langfuse payload validation. The skill should recommend opt-in aliases until those checks pass.

**Principle:** Provider centralisation only helps if quality, observability, and cost accounting survive the abstraction boundary; each must be validated directly.

### Observation 2: Decouple general quality aliases from model-specific test asserts

**Date:** 2026-06-03
**Session context:** Integrated Reve as a new image generation provider and set it as the default for `image-quality`.
**Skill:** New skill candidate: test-isolation-principles
**Type:** internal
**Phase/Area:** Test suite stability & model-specific verification

**Issue:** Several unit tests that were meant to test GPT-2 prompt formatting and token pricing calculations used the general `"image-quality"` alias because it originally mapped to `"openai/gpt-image-2"`. When the default of `"image-quality"` was flipped to `"reve"`, all of these tests broke since `"reve"` does not use token pricing or the GPT-2 formatting guardrails.

**Suggested improvement:** Require unit tests that verify model-specific features or behaviors (such as specific pricing logic or specific prompt templates) to target the exact backend model name directly (e.g. `"openai/gpt-image-2"`) rather than general gateway aliases (e.g. `"image-quality"`). The general aliases should only be used in tests verifying alias resolution or default fallback paths.

**Principle:** Test assertions about model-specific behavior must be bound to the specific model identifier, preventing routing/alias configuration updates from breaking unrelated parts of the test suite.

### Observation 3: Support layout prompt formats in custom LLM providers

**Date:** 2026-06-03
**Session context:** Added support for Reve's layout prompt endpoint (`POST /v1/image/layout`).
**Skill:** New skill candidate: api-controllability-mapping
**Type:** internal
**Phase/Area:** API custom handlers

**Issue:** Model providers are evolving to accept more structured intermediate representations (such as JSON layouts) rather than just plain text prompts to enable granular spatial control (positioning, regional prompts, etc.). If custom LiteLLM handlers only implement standard text-to-image `/v1/image/create` endpoints, they miss out on these structured controllability features.

**Suggested improvement:** Ensure custom LLM handlers dynamically check input prompts (e.g. attempting to parse JSON strings) or parameters for structured layout attributes, routing to specialized layout endpoints (e.g., `/v1/image/layout` with layout2image, text2layout, etc.) as needed, while falling back gracefully to standard generation routes.

**Principle:** Modern visual generation APIs bridge semantic intent and pixel rendering through intermediate data formats like layouts; custom handlers must support these structured pipelines to preserve complete controllability.



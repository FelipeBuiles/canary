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

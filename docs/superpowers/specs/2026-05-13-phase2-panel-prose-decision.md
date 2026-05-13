# Phase 2 Distilled Prompt Decision

Date: 2026-05-13

## Decision

Use deterministic distilled prompts as the production image-generation brief.
Each structured `ImagePrompt` stores a compact `distilled_prompt` compiled from
composition, visible subjects, action/expression, setting, lighting, mood, and
the most important visual requirements. Keep `full_prompt` as the structured
debug/comparison fallback.

## Why

Phase 1 confirmed Seedream can run through the LiteLLM proxy with the tracking
metadata we need. The prompt-quality issue is now the main production variable:
Labs fixtures written as natural panel directions outperform the current
labelled renderer even on the same image model.

Testing showed the LLM prose rewrite did not improve image quality. The
deterministic distilled compiler did: it keeps the prompt focused on one
drawable image idea, drops caption-layout instructions, avoids constraint
overload, and costs nothing at direct time. The storyboard-schema change is
still a possible long-term source of richer visual briefs, but the current
distilled compiler is good enough to become the default.

## Implementation Shape

- Add `ImagePrompt.distilled_prompt`.
- Compile distilled prompts deterministically in the `direct` stage and whenever
  a panel prompt is edited or instruction-regenerated.
- Make draw use `distilled_prompt` when present, otherwise use the existing
  structured prompt rendering.
- Keep only essential constraints in distilled generation prompts.
- Strip caption-space instructions and dangling truncated clauses from
  distilled output.
- Treat direct-stage prompt assembly as zero text-model cost.
- Make Labs imported scenes use the distilled prompt as the primary prompt, with
  the structured prompt available as the comparison variant.

## Validation

Use Labs prompt A/B with Seedream on representative scenes: distilled prompt
versus current structured prompt. Ship with distilled as the default once it is
consistently equal or better in visual quality and does not drop story-critical
details.

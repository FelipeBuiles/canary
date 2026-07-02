# Taste (Continuously Learned by [CommandCode][cmd])

[cmd]: https://commandcode.ai/

# workflow
- Fix multiple related issues in a single pass rather than iterating message-by-message. Confidence: 0.85
- Use handoff documents to carry architecture and approach only (not full session replay) when starting a new session on a related task. Confidence: 0.75

# prompting
- Use prose-style flowing descriptions for image generation prompts, not labeled key:value clauses (e.g. avoid "Composition: X. Setting: Y." format). Confidence: 0.80
- Use positive phrasing in image generation constraints instead of enumerating failure modes (do not say "avoid stochastic grain, artifacts, speckled dappling"). Confidence: 0.75
- For prompt/text assembly tasks (not complex reasoning), disable reasoning_effort to avoid token budget exhaustion and leaked chain-of-thought. Confidence: 0.70

# image-generation
- For Reve layout-aware API, use flat regions with bbox coordinates (not nested hierarchical regions). Confidence: 0.80
- Use fewer, cleaner reference images (individual crops) rather than sheet grids that can leak layout into output. Confidence: 0.70
- Use config feature flags (e.g. `visual_brief_enabled: bool`) for new LLM passes so quality experiments can be toggled per project. Confidence: 0.65

# debugging
- Surface diagnostic details (finish_reason, safety_ratings, error signatures) before guessing at failure causes. Confidence: 0.75
- After changing gateway config (litellm/config.yaml or litellm_handlers/), run `docker compose restart litellm` (not just `docker compose up -d`) since config is bind-mounted read-only and read at startup. Confidence: 0.70


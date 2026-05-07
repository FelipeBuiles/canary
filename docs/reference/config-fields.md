# Config Fields Reference

_Maintained manually. Sync changes with `config.py`._

## Priority (highest → lowest)

1. Shell environment variables
2. Nearest `.env` file (walked up from project_dir)
3. `config.yaml` in project directory
4. Pydantic field defaults

Load with `load_config(project_dir) → (Config, env_file_path)`.

## Fields

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `litellm_base_url` | `str` | `'http://localhost:4000'` | LiteLLM Proxy base URL |
| `litellm_api_key` | `str` | `'sk-local-canary'` | LiteLLM Proxy API key; never returned unmasked by config API |
| `ai_bill_failed_requests` | `Literal` | `'provider_usage_only'` | Failed/refused billing policy: `provider_usage_only` \| `never` \| `estimate_all` |
| `google_use_vertex_ai` | `bool` | `True` | Use Vertex AI ADC instead of Gemini developer API |
| `google_cloud_project` | `str` | `''` | Google Cloud project ID for Vertex AI |
| `google_cloud_location` | `str` | `'global'` | Vertex AI location |
| `extraction_model` | `str` | `'canary/extract'` | Stage 1 gateway alias |
| `screenplay_model` | `str` | `'canary/screenplay'` | Stage 3 gateway alias |
| `panel_model` | `str` | `'canary/panel'` | Stage 4/5 gateway alias |
| `prompt_model` | `str` | `'canary/prompt'` | Stage 6 gateway alias |
| `quality_preset` | `QualityPreset or None` | `None` | Overrides all four text model fields. `fast` \| `balanced` \| `quality`. `dev_mode` forces `fast`. **Note:** All three presets currently resolve to the same gateway aliases — this is transitional during the LiteLLM migration; the LiteLLM `config.yaml` maps each alias to the appropriate model per deployment. |
| `image_provider` | `Literal` | `'gemini'` | Legacy metadata field; runtime image calls use LiteLLM |
| `image_model` | `str` | `'canary/image-primary'` | Primary image gateway alias |
| `fallback_image_model` | `str` | `'canary/image-fallback'` | Fallback image gateway alias (used in dev mode) |
| `dev_mode` | `bool` | `False` | Faster iteration: lower resolution/steps, uses fallback_image_model |
| `dev_image_scale` | `float` | `0.5` | Scale factor for dev mode image dimensions |
| `dev_image_steps` | `int` | `8` | Reduced diffusion steps in dev mode |
| `dev_image_concurrency` | `int` | `5` | Max concurrent image requests in dev mode |
| `image_width` | `int` | `1024` | Target image width (Gemini ignores; Together/OpenAI respect it) |
| `image_height` | `int` | `1024` | Target image height |
| `image_steps` | `int` | `28` | Inference steps |
| `image_quality` | `str` | `'medium'` | OpenAI GPT Image quality: `auto` \| `low` \| `medium` \| `high` |
| `flux_guidance_scale` | `float` | `3.5` | Guidance scale for FLUX/Together AI models |
| `continuity_mode` | `str` | `'hybrid'` | Character consistency mode: `off` \| `text_only` \| `ref_only` \| `hybrid` |
| `negative_prompt` | `str` | `'ugly, deformed, blurry, ...'` | Applied to Together AI / SDXL models only (Gemini ignores) |
| `style_template` | `str` | `'High quality visual storytelling. ...'` | Injected verbatim at start of every image prompt |
| `plan_mode` | `Literal` | `'llm'` | Stage 4 planning mode: `llm` \| `heuristic` |
| `max_panels_per_scene` | `int` | `8` | Cap on panels per scene |
| `max_panels_per_page` | `int` | `6` | Panels per assembled comic page |
| `max_words_per_bubble` | `int` | `35` | Max words per dialogue bubble |
| `parallel_batch_size` | `int` | `5` | Scenes to process in parallel (stages 3–6) |
| `max_concurrent_requests` | `int` | `5` | Max simultaneous image generation requests (stage 7) |
| `cost_limit_usd` | `Optional[float]` | `None` | Hard cap — pipeline pauses if total cost exceeds this |
| `comic_theme` | `str` | `'auto'` | Comic theme: `auto` \| `default` \| `noir` \| `manga` \| `vintage` \| `painted` |
| `target_language` | `str` | `'en'` | Output language for generated text: `en` \| `es` \| `fr` |

## Gateway Routing

Runtime AI calls go through `novel_to_comic.ai.client`, which calls LiteLLM
OpenAI-compatible endpoints and records `ai_usage_events`.

### Text aliases

| Alias | Purpose |
|-------|---------|
| `canary/extract` | Story bible extraction |
| `canary/screenplay` | Screenplay adaptation |
| `canary/panel` | Layout planning and panel breakdown |
| `canary/prompt` | Prompt rewrite, style, translation, and instruction tasks |

### Image aliases

| Alias | Purpose |
|-------|---------|
| `canary/image-primary` | Production image generation |
| `canary/image-fallback` | Fallback image generation (used in dev mode) |
| `canary/image-fast` | Legacy dev-mode alias (superseded by `canary/image-fallback`) |

## Environment Variables

| Variable | Maps to |
|----------|---------|
| `LITELLM_BASE_URL` | `litellm_base_url` |
| `LITELLM_API_KEY` | `litellm_api_key` |
| `AI_BILL_FAILED_REQUESTS` | `ai_bill_failed_requests` |
| `GOOGLE_CLOUD_PROJECT` | `google_cloud_project` |
| `GOOGLE_CLOUD_LOCATION` | `google_cloud_location` |
| `GOOGLE_GENAI_USE_VERTEXAI` | `google_use_vertex_ai` |

Provider API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`,
`OPENROUTER_API_KEY`, `TOGETHER_API_KEY`) belong in the LiteLLM service
environment, not Canary runtime config.

## Pricing

The local `pricing.yaml` file has been removed. Cost lookup now uses:

- `litellm_model_prices.cached.json` — LiteLLM model pricing cache
  (downloaded from the LiteLLM pricing endpoint at startup).
- `litellm_pricing_overrides.yaml` — project-specific overrides for models
  not in the LiteLLM cache or with custom pricing (e.g. input image costs).

`audit_pricing()` on startup validates that all configured gateway aliases have
pricing entries.

## Config API Allowlist

The `PATCH /config` endpoint accepts updates only for fields listed in
`_SETTABLE_FIELDS` (defined in `server/routers/config.py`). Any field not in
the allowlist is silently ignored. The current allowlist:

```
quality_preset, target_language, style_template, dev_mode, image_provider,
image_model, fallback_image_model, image_quality, image_steps,
continuity_mode, plan_mode, comic_theme, negative_prompt,
max_panels_per_scene, max_panels_per_page, max_words_per_bubble,
parallel_batch_size, max_concurrent_requests, cost_limit_usd,
flux_guidance_scale
```

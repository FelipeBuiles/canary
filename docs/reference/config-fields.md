# Config Fields Reference
_Auto-generated from `config.py`. Do not edit manually._

## Priority (highest → lowest)
1. Shell environment variables
2. Nearest `.env` file (walked up from project_dir)
3. `config.yaml` in project directory
4. Pydantic field defaults

Load with `load_config(project_dir) → (Config, env_file_path)`.

## Fields

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `litellm_base_url` | `str` | `'http://localhost:4000'` |  |
| `litellm_api_key` | `str` | `'sk-local-canary'` |  |
| `ai_bill_failed_requests` | `FailedRequestBillingPolicy` | `'provider_usage_only'` |  |
| `google_use_vertex_ai` | `bool` | `True` |  |
| `google_cloud_project` | `str` | `''` |  |
| `google_cloud_location` | `str` | `'global'` |  |
| `extraction_model` | `str` | `GATEWAY_EXTRACT_BALANCED` |  |
| `screenplay_model` | `str` | `GATEWAY_SCREENPLAY_BALANCED` |  |
| `panel_model` | `str` | `GATEWAY_PANEL_BALANCED` |  |
| `prompt_model` | `str` | `GATEWAY_PROMPT_BALANCED` |  |
| `image_provider` | `Literal['gemini', 'openai', 'openrouter', 'together', 'reve']` | `'gemini'` |  |
| `image_model` | `str` | `GATEWAY_IMAGE_QUALITY` | New-project default quality image route (Gemini 3 Pro Image / Nano Banana 2 Pro). |
| `fallback_image_model` | `str` | `GATEWAY_IMAGE_FAST` |  |
| `target_language` | `str` | `'en'` |  |
| `dev_mode` | `bool` | `False` |  |
| `quality_preset` | `QualityPreset | None` | `None` |  |
| `dev_image_scale` | `float` | `0.5` |  |
| `dev_image_steps` | `int` | `8` |  |
| `dev_image_concurrency` | `int` | `5` |  |
| `image_width` | `int` | `1024` |  |
| `image_height` | `int` | `1024` |  |
| `image_steps` | `int` | `28` |  |
| `image_quality` | `str` | `'medium'` | OpenAI GPT Image quality: auto | low | medium | high |
| `flux_guidance_scale` | `float` | `3.5` |  |
| `continuity_mode` | `str` | `'hybrid'` | off | text_only | ref_only | hybrid |
| `image_concurrency` | `int | None` | `None` |  |
| `visual_brief_enabled` | `bool` | `True` |  |
| `style_sample_brief_enabled` | `bool` | `True` |  |
| `layout_prompts_enabled` | `bool` | `False` | Set to `true` for newly compiled Reve v2 `render_layout` panels; the endpoint is experimental. Existing frozen requests remain exact. |
| `negative_prompt` | `str` | `'ugly, deformed, blurry, bad anatomy, watermark, signatur...` |  |
| `style_template` | `str` | `'High quality visual storytelling. Dramatic natural light...` |  |
| `max_panels_per_scene` | `int` | `8` |  |
| `max_panels_per_page` | `int` | `6` | how many panels appear on each assembled page |
| `max_words_per_bubble` | `int` | `24` | maximum dialogue/thought words before adaptation splits the beat |
| `parallel_batch_size` | `int` | `5` |  |
| `max_concurrent_requests` | `int` | `5` |  |
| `cost_limit_usd` | `Optional[float]` | `None` |  |

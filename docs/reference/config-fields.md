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
| `_one_shot_image_model_alias` | `str | None` | `PrivateAttr(default=None)` |  |
| `litellm_base_url` | `str` | `'http://localhost:4000'` |  |
| `litellm_api_key` | `str` | `'sk-local-canary'` |  |
| `ai_bill_failed_requests` | `FailedRequestBillingPolicy` | `'provider_usage_only'` |  |
| `mock_mode` | `bool` | `False` |  |
| `mock_model_base_url` | `str` | `'http://127.0.0.1:4010'` |  |
| `google_use_vertex_ai` | `bool` | `True` |  |
| `google_cloud_project` | `str` | `''` |  |
| `google_cloud_location` | `str` | `'global'` |  |
| `dev_model_selections` | `dict[str, str]` | `Field(default_factory=dict)` |  |
| `extraction_model` | `str` | `GATEWAY_GEMINI_FLASH` |  |
| `extraction_chunk_chars` | `int` | `Field(default=16000, ge=4000, le=64000)` |  |
| `brief_model` | `str` | `GATEWAY_LUNA` |  |
| `adapt_model` | `str` | `GATEWAY_TERRA` |  |
| `plan_model` | `str` | `GATEWAY_TERRA` |  |
| `narrative_max_calls` | `int | None` | `Field(default=None, ge=1)` |  |
| `prompt_model` | `str` | `GATEWAY_LUNA` |  |
| `page_ocr_model` | `str` | `GATEWAY_PAGE_OCR` |  |
| `visual_review_model` | `str` | `GATEWAY_PAGE_OCR` |  |
| `image_provider` | `Literal['gemini', 'openai', 'openrouter', 'together']` | `'gemini'` |  |
| `image_model` | `str` | `GATEWAY_IMAGE_BALANCED` |  |
| `draw_model` | `str` | `GATEWAY_IMAGE_BALANCED` |  |
| `target_language` | `str` | `'en'` |  |
| `dev_mode` | `bool` | `False` |  |
| `dev_image_scale` | `float` | `0.5` |  |
| `dev_image_steps` | `int` | `8` |  |
| `dev_image_concurrency` | `int` | `5` |  |
| `image_width` | `int` | `1024` |  |
| `image_height` | `int` | `1024` |  |
| `image_steps` | `int` | `28` |  |
| `image_quality` | `str` | `'medium'` | OpenAI GPT Image quality: auto | low | medium | high |
| `flux_guidance_scale` | `float` | `3.5` |  |
| `image_concurrency` | `int | None` | `None` |  |
| `visual_brief_enabled` | `bool` | `False` |  |
| `style_sample_brief_enabled` | `bool` | `True` |  |
| `negative_prompt` | `str` | `'ugly, deformed, blurry, bad anatomy, watermark, signatur...` |  |
| `style_template` | `str` | `'High quality visual storytelling. Dramatic natural light...` |  |
| `parallel_batch_size` | `int` | `5` |  |
| `max_concurrent_requests` | `int` | `5` |  |
| `cost_limit_usd` | `Optional[float]` | `None` |  |

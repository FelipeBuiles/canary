# Config Fields Reference
_Auto-generated from `config.py`. Do not edit manually._

## Priority (highest → lowest)
1. Shell environment variables
2. Nearest `.env` file (walked up from project_dir)
3. Project-owned values in `config.yaml` (model routes and gateway credentials are ignored)
4. Pydantic field defaults

Production stage models are overlaid from operator settings when a job config is created. Load with `load_config(project_dir) → (Config, env_file_path)`.

## Fields

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `_one_shot_image_model_alias` | `str | None` | `PrivateAttr(default=None)` |  |
| `litellm_base_url` | `str` | `'http://localhost:4000'` |  |
| `litellm_api_key` | `str` | `'sk-local-canary'` |  |
| `text_reasoning_efforts` | `dict[str, str]` | `Field(default_factory=dict)` |  |
| `text_reasoning_effort` | `Literal['low', 'medium', 'high']` | `'medium'` |  |
| `ai_bill_failed_requests` | `FailedRequestBillingPolicy` | `'provider_usage_only'` |  |
| `mock_mode` | `bool` | `False` |  |
| `mock_model_base_url` | `str` | `'http://127.0.0.1:4010'` |  |
| `dev_model_selections` | `dict[str, str]` | `Field(default_factory=dict)` |  |
| `extraction_model` | `str` | `GATEWAY_GEMINI_FLASH` |  |
| `extraction_chunk_chars` | `int` | `Field(default=16000, ge=4000, le=64000)` |  |
| `brief_model` | `str` | `GATEWAY_GEMINI_FLASH` |  |
| `adapt_model` | `str` | `GATEWAY_SOL` |  |
| `plan_model` | `str` | `GATEWAY_SOL` |  |
| `narrative_max_calls` | `int | None` | `Field(default=None, ge=1)` |  |
| `prompt_model` | `str` | `GATEWAY_LUNA` |  |
| `page_ocr_model` | `str` | `GATEWAY_PAGE_OCR` |  |
| `visual_review_model` | `str` | `GATEWAY_PAGE_OCR` |  |
| `correction_model` | `str` | `CORRECTION_INTERPRETER_MODEL` |  |
| `image_model` | `str` | `GATEWAY_IMAGE_SUNBURST` |  |
| `draw_model` | `str` | `GATEWAY_IMAGE_SUNBURST` |  |
| `target_language` | `Language` | `'en'` |  |
| `lettering_mode` | `Literal['editable', 'integrated']` | `'editable'` |  |
| `dev_mode` | `bool` | `False` |  |
| `dev_image_concurrency` | `int` | `DEFAULT_IMAGE_CONCURRENCY` |  |
| `image_quality` | `str` | `'medium'` | OpenAI GPT Image quality: auto | low | medium | high |
| `image_concurrency` | `int | None` | `DEFAULT_IMAGE_CONCURRENCY` |  |
| `style_sample_brief_enabled` | `bool` | `True` |  |
| `style_template` | `str` | `'High quality visual storytelling. Dramatic natural light...` |  |
| `parallel_batch_size` | `int` | `DEFAULT_TEXT_CONCURRENCY` |  |
| `max_concurrent_requests` | `int` | `DEFAULT_TEXT_CONCURRENCY` | Text ceiling; transport admission also enforces provider budgets |
| `adapt_concurrency` | `int` | `DEFAULT_ADAPT_CONCURRENCY` |  |
| `cost_limit_usd` | `Optional[float]` | `None` |  |

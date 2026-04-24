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
| `gemini_api_key` | `str` | `''` | Gemini developer API key (legacy; Vertex AI ADC preferred) |
| `anthropic_api_key` | `str` | `''` | Anthropic API key for Claude (stage 3) |
| `together_api_key` | `str` | `''` | Together AI API key (FLUX via Together) |
| `openai_api_key` | `str` | `''` | OpenAI API key (GPT Image models) |
| `openrouter_api_key` | `str` | `''` | OpenRouter API key (various models) |
| `google_use_vertex_ai` | `bool` | `True` | Use Vertex AI ADC instead of Gemini developer API |
| `google_cloud_project` | `str` | `''` | Google Cloud project ID for Vertex AI |
| `google_cloud_location` | `str` | `'global'` | Vertex AI location |
| `extraction_model` | `str` | `'gemini-3.1-pro-preview'` | Stage 1 — full-novel extraction |
| `screenplay_model` | `str` | `'gemini-3.1-pro-preview'` | Stage 3 — screenplay adaptation |
| `panel_model` | `str` | `'gemini-3.1-flash-lite-preview'` | Stage 5 — panel breakdown |
| `prompt_model` | `str` | `'gemini-3.1-flash-lite-preview'` | Stage 6 — image prompt assembly |
| `embedding_model` | `str` | `'gemini-embedding-001'` | Google Vertex AI, 3072 dims |
| `image_provider` | `Literal` | `'gemini'` | Image gen provider: `gemini` \| `openai` \| `openrouter` \| `together` |
| `image_model` | `str` | `'gemini-3-pro-image-preview'` | Primary image generation model |
| `fallback_image_model` | `str` | `'gemini-3.1-flash-image-preview'` | Dev-mode fallback for image generation |
| `dev_mode` | `bool` | `False` | Faster iteration: lower resolution/steps, uses fallback_image_model |
| `dev_image_scale` | `float` | `0.5` | Scale factor for dev mode image dimensions |
| `dev_image_steps` | `int` | `8` | Reduced diffusion steps in dev mode |
| `dev_image_concurrency` | `int` | `5` | Max concurrent image requests in dev mode |
| `image_width` | `int` | `1024` | Target image width (Gemini ignores; Together/OpenAI respect it) |
| `image_height` | `int` | `1024` | Target image height |
| `image_steps` | `int` | `28` | Inference steps |
| `image_quality` | `str` | `'auto'` | OpenAI GPT Image quality: `auto` \| `low` \| `medium` \| `high` |
| `flux_guidance_scale` | `float` | `3.5` | Guidance scale for FLUX/Together AI models |
| `continuity_mode` | `str` | `'hybrid'` | Character consistency mode: `off` \| `text_only` \| `ref_only` \| `hybrid` |
| `negative_prompt` | `str` | `'ugly, deformed, blurry, ...'` | Applied to Together AI / SDXL models only (Gemini ignores) |
| `style_template` | `str` | `'High quality visual storytelling. ...'` | Injected verbatim at start of every image prompt |
| `enable_rag_index` | `bool` | `False` | Build optional Qdrant vector index in Stage 2 |
| `max_panels_per_scene` | `int` | `8` | Cap on panels per scene |
| `max_panels_per_page` | `int` | `6` | Panels per assembled comic page |
| `max_words_per_bubble` | `int` | `35` | Max words per dialogue bubble |
| `parallel_batch_size` | `int` | `5` | Scenes to process in parallel (stages 3–6) |
| `qdrant_host` | `str` | `'localhost'` | Qdrant vector store host |
| `qdrant_port` | `int` | `6333` | Qdrant port |
| `max_concurrent_requests` | `int` | `5` | Max simultaneous image generation requests (stage 7) |
| `cost_limit_usd` | `Optional[float]` | `None` | Hard cap — pipeline pauses if total cost exceeds this |
| `comic_theme` | `str` | `'auto'` | Comic theme: `auto` \| `default` \| `noir` \| `manga` \| `vintage` \| `painted` |
| `target_language` | `str` | `'en'` | Output language for generated text: `en` \| `es` \| `fr` |

## Provider Routing

The `image_provider` field controls which API is used for image generation:

| Provider | How identified | Example models |
|----------|---------------|----------------|
| `gemini` (default) | `image_provider == "gemini"` | `gemini-3-pro-image-preview`, `gemini-3.1-flash-image-preview` |
| `openai` | `gpt-image-*` in model name | `gpt-image-1`, `gpt-image-1.5` |
| `openrouter` | `/` in model name + provider `"openrouter"` | `black-forest-labs/flux-1-dev` |
| `together` | `/` in model name + provider `"together"` | `black-forest-labs/FLUX.1-kontext-pro` |

## Environment Variables

| Variable | Maps to |
|----------|---------|
| `GEMINI_API_KEY` | `gemini_api_key` |
| `ANTHROPIC_API_KEY` | `anthropic_api_key` |
| `TOGETHER_API_KEY` | `together_api_key` |
| `OPENAI_API_KEY` | `openai_api_key` |
| `OPENROUTER_API_KEY` | `openrouter_api_key` |
| `GOOGLE_CLOUD_PROJECT` | `google_cloud_project` |
| `GOOGLE_CLOUD_LOCATION` | `google_cloud_location` |
| `GOOGLE_GENAI_USE_VERTEXAI` | `google_use_vertex_ai` |

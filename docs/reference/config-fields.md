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
| `gemini_api_key` | `str` | `''` |  |
| `anthropic_api_key` | `str` | `''` |  |
| `together_api_key` | `str` | `''` |  |
| `openai_api_key` | `str` | `''` |  |
| `google_use_vertex_ai` | `bool` | `True` | Use Vertex AI ADC instead of Gemini Developer API keys |
| `google_cloud_project` | `str` | `''` | Google Cloud project ID for Vertex AI |
| `google_cloud_location` | `str` | `'global'` | Vertex AI location |
| `extraction_model` | `str` | `'gemini-3.1-pro-preview'` |  |
| `screenplay_model` | `str` | `'gemini-3.1-pro-preview'` |  |
| `panel_model` | `str` | `'gemini-3.1-flash-lite-preview'` |  |
| `prompt_model` | `str` | `'gemini-3.1-flash-lite-preview'` |  |
| `enable_rag_index` | `bool` | `False` | Build optional Qdrant scene index during Stage 2 |
| `embedding_model` | `str` | `'gemini-embedding-001'` | Google Vertex AI, 3072 dims |
| `image_model` | `str` | `'gemini-3-pro-image-preview'` | Nano Banana Pro — Gemini 3 Pro Image (native) |
| `fallback_image_model` | `str` | `'gemini-3.1-flash-image-preview'` | Nano Banana 2 — faster dev image model |
| `image_width` | `int` | `1024` |  |
| `image_height` | `int` | `1024` |  |
| `image_steps` | `int` | `28` |  |
| `flux_guidance_scale` | `float` | `3.5` |  |
| `negative_prompt` | `str` | `'ugly, deformed, blurry, bad anatomy, watermark, signatur...` |  |
| `style_template` | `str` | `'High quality visual storytelling. Dramatic natural light...` |  |
| `max_panels_per_scene` | `int` | `8` |  |
| `max_panels_per_page` | `int` | `6` | how many panels appear on each assembled page |
| `max_words_per_bubble` | `int` | `35` |  |
| `parallel_batch_size` | `int` | `5` |  |
| `qdrant_host` | `str` | `'localhost'` |  |
| `qdrant_port` | `int` | `6333` |  |
| `max_concurrent_requests` | `int` | `5` |  |
| `cost_limit_usd` | `Optional[float]` | `None` |  |
| `comic_theme` | `str` | `'auto'` |  |

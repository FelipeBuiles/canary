# Novel-to-Comic Pipeline

An 8-stage Python/FastAPI/React application that converts a novel
(EPUB, TXT, or PDF) into a graphic novel (PDF/CBZ), using LLMs for story
analysis and image generation models for panel artwork.

**Cost estimate:** ~$25–35 for a 300-page novel (600 panels) at standard quality.  
**PoC cost:** ~$2–5 for a 10-page short story (15–20 panels).

---

## Architecture

```
Novel (EPUB / TXT / PDF)
  │
  ▼ Stage 1 — Extract (gemini-3.1-pro-preview, 1M context)
  │   Full novel → Story Bible JSON
  │   Characters (visual anchors), locations, scenes, narrative arcs, props
  │   ► CHECKPOINT: review story_bible.json before continuing
  │
  ▼ Stage 2 — Cast (image gen via config.image_provider)
  │   Character reference sheets (4 angles each) + location background plates
  │   ► CHECKPOINT: review refs/ and plates/ before continuing
  │
  ▼ Stage 3 — Adapt (gemini-3.1-pro-preview)
  │   Per-scene: prose → observable actions, compressed dialogue (≤35 words/bubble)
  │   Removes interiority; adds SFX annotations
  │
  ▼ Stage 4 — Plan (deterministic — no LLM)
  │   Screenplay → Layout Plan JSON (planned pages + planned panels)
  │   Assigns panel geometry, page layout, generation modes
  │
  ▼ Stage 5 — Storyboard (gemini-3.1-flash-lite-preview)
  │   Layout plan → legacy PanelBreakdown JSON per panel
  │   Shot type, camera angle, character positions, expressions, dialogue
  │
  ▼ Stage 6 — Direct (gemini-3.1-flash-lite-preview)
  │   Per-panel: assembles full image prompt from:
  │     [Style template] + [Location anchor] + [Character anchor(s)] + [Panel description]
  │   Character visual anchors injected VERBATIM for consistency
  │
  ▼ Stage 7 — Draw (image gen via config.image_provider)
  │   Per-panel: prompt + reference images → panel PNG
  │   ► CHECKPOINT: review generated images before continuing
  │
  ▼ Stage 8 — Compose (deterministic — Playwright + Pillow)
      Panel images + bubble/SFX → HTML → PNG pages → PDF/CBZ export
      Speech bubbles, thought bubbles, narration captions, SFX composited in post
```

### Key Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Character anchors are sacred** | 60–80 word physical description injected verbatim into every image prompt. Never paraphrased. |
| **Text in post** | Speech bubbles composited in Stage 8 — never generated inside images. |
| **Layout plan as planner** | Stage 4 owns page/panel structure; downstream stages project from it. |
| **Decompose relentlessly** | Each LLM call does exactly one thing. No end-to-end generation. |
| **Human checkpoints at boundaries** | Pipeline pauses after `extract`, `cast`, `direct`, and `draw`. |
| **Resume from failure** | `state.json` tracks every item. Interrupted stages resume where they left off. |

---

## Model Choices

Defaults in `config.py`, overridable in `config.yaml`.

### Text / LLM stages

| Stage | Model | Why |
|-------|-------|-----|
| Extract (1) | `gemini-3.1-pro-preview` | 1M context window fits a full novel in one pass |
| Adapt (3) | `gemini-3.1-pro-preview` | Creative writing quality for screenplay adaptation |
| Storyboard (5) | `gemini-3.1-flash-lite-preview` | Structured JSON, fast and cheap |
| Direct (6) | `gemini-3.1-flash-lite-preview` | Template assembly, Flash-Lite sufficient |
| Embeddings | `gemini-embedding-001` | Google Vertex AI, 3072 dims |
| Vector store | Qdrant | Hybrid search (dense + BM25), optional — disabled by default |

### Image generation

Configured via two fields in `config.yaml`:

```yaml
image_provider: "gemini"   # gemini | openai | openrouter | together
image_model: "gemini-3-pro-image-preview"   # provider-specific model ID
```

| Provider | Model examples | Routing rule |
|----------|---------------|-------------|
| Gemini (default) | `gemini-3-pro-image-preview`, `gemini-3.1-flash-image-preview` | `image_provider == "gemini"` |
| OpenAI | `gpt-image-1`, `gpt-image-1.5` | model name starts with `gpt-image-` |
| OpenRouter | `black-forest-labs/flux-1-dev`, etc. | `/` in model name + provider == `"openrouter"` |
| Together AI | `black-forest-labs/FLUX.1-kontext-pro`, etc. | `/` in model name + provider == `"together"` |

---

## Installation

**Requirements:** Python 3.12+, Docker (optional, for Qdrant)

```bash
git clone <repo>
cd canary/novel_to_comic

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e .

# One-time: install Playwright Chromium browser (required for Stage 8 — HTML → PNG rendering)
playwright install chromium
```

Qdrant is optional and disabled by default. To enable it:

```bash
docker run -d --name qdrant \
  -p 6333:6333 \
  -v ./qdrant_data:/qdrant/storage \
  qdrant/qdrant:latest
```

---

## Setup

### 1. Initialise a project

```bash
cd my-project-dir
pipeline init ../path/to/novel.epub
```

This creates the project directory with `config.yaml`, `state.json`, and all
required subdirectories.

### 2. Configure API keys

The pipeline uses [Application Default Credentials (ADC)](https://cloud.google.com/docs/authentication/application-default-credentials) for Google Gemini by default.

```bash
# Google — ADC (no key needed on local machine with gcloud auth)
gcloud auth application-default login

# Or set a service account JSON directly
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
export GOOGLE_GENAI_USE_VERTEXAI=true
export GOOGLE_CLOUD_PROJECT=your-project-id
export GOOGLE_CLOUD_LOCATION=global

# For other providers, put keys in .env at your repo root (not per-project)
echo "ANTHROPIC_API_KEY=sk-ant-..." >> .env
echo "TOGETHER_API_KEY=..." >> .env
echo "OPENAI_API_KEY=..." >> .env
```

`.env.example` in the project root shows all available key variables. The pipeline
walks up from any project directory to find the nearest `.env`.

### 3. Optional: OpenTelemetry tracing

Canary emits OpenTelemetry spans for outbound API calls (Gemini, Together, OpenAI,
Anthropic) with redacted structured parameters.

```bash
pip install -e '.[web,otel]'

export CANARY_OTEL_ENABLED=1
export OTEL_SERVICE_NAME=canary
export OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf
export OTEL_EXPORTER_OTLP_ENDPOINT='https://<your-otlp-endpoint>'
export OTEL_EXPORTER_OTLP_HEADERS='Authorization=Basic%20<base64(instance_id:token)>'
```

Notes:
- For Python, use `Basic%20` (not `Basic `) in `OTEL_EXPORTER_OTLP_HEADERS`.
- Keep `CANARY_LOG_INCLUDE_PROMPTS` unset in production to avoid logging prompt text.

---

## Running the Pipeline

There is no `pipeline run <stage>` CLI command. All pipeline operations go through
the FastAPI web server.

### Start the web server

```bash
pipeline serve --projects-dir /path/to/projects [--host 0.0.0.0 --port 8000]
```

Then open `http://localhost:8000` in your browser. The web UI provides:
- Project library with status and cost tracking
- 8 rooms (one per pipeline stage) with per-artifact viewers and editors
- Pipeline run/approve/reset controls
- Live SSE streaming of stage progress
- Stage 8 page editor with bubble/SFX editing, theme switching, and export

### Run stages via API

```bash
# Run all stages from current state
curl -X POST "http://localhost:8000/api/projects/my-novel/run"

# Run a specific stage (clears downstream outputs)
curl -X POST "http://localhost:8000/api/projects/my-novel/run?stage=draw"

# Approve a checkpoint stage
curl -X POST "http://localhost:8000/api/projects/my-novel/approve/extract"

# Reset a stale stage
curl -X POST "http://localhost:8000/api/projects/my-novel/reset/extract"

# Check pipeline status
curl "http://localhost:8000/api/projects/my-novel/status"

# Export to PDF / CBZ
curl -X POST "http://localhost:8000/api/projects/my-novel/export"
curl "http://localhost:8000/api/projects/my-novel/export/pdf" -o comic.pdf
```

SSE event stream (connect before triggering a run):

```bash
curl "http://localhost:8000/api/projects/my-novel/events"
```

---

## Project Directory Structure

```
projects/my-novel/
├── config.yaml              # API keys + pipeline config
├── state.json               # Stage progress, costs, failed items
├── story_bible.json         # Central artifact — all downstream stages read this
├── input/
│   └── novel.epub
├── scenes/                  # Extracted scene text files (scene_001.txt …)
├── refs/                    # Character reference sheets
│   └── char_NNN/
│       ├── front.png
│       ├── three_quarter.png
│       ├── side.png
│       └── action.png
├── plates/                  # Location background plates (loc_NNN.png …)
├── adapt/                   # Per-scene screenplay JSON
│   └── scene_NNN.json
├── plan/
│   └── layout_plan.json     # Planner-owned page/panel structure
├── storyboard/              # Per-panel breakdown JSON (legacy compat from plan)
│   └── scene_NNN/
│       └── panel_NNN.json
├── direct/                  # Per-panel image prompt JSON
│   └── scene_NNN/
│       └── panel_NNN.json
├── draw/                    # Generated panel images
│   └── scene_NNN/
│       └── panel_NNN.png
├── compose/                 # Stage 8 output
│   ├── theme.css           # Editable CSS — re-export to apply changes
│   ├── pages/
│   │   ├── page_NNN.json   # Canonical editing surface (ComicPage model)
│   │   └── page_NNN.png   # Rendered preview
│   └── html/
│       └── page_NNN.html   # HTML preview — open in browser, edit CSS, hard-refresh
└── exports/
    ├── comic.pdf
    └── comic.cbz
```

---

## Stage 8 Editing (compose)

Stage 8 produces `compose/pages/page_NNN.json` — the **editing surface** for every
comic page. Edit these files directly (or via the web UI) and re-export to
re-render without re-running earlier stages.

### ComicPage JSON structure

```json
{
  "page_number": 1,
  "theme": "noir",
  "layout": "4",
  "panels": [
    {
      "id": "scene_001-003",
      "image_path": "draw/scene_001/panel_003.png",
      "scene_id": "scene_001",
      "panel_number": 3,
      "grid_column": null,
      "sfx": null,
      "bubbles": [
        {
          "id": "scene_001-p3-b0",
          "type": "speech",
          "text": "I'll be back.",
          "speaker_id": "char_001",
          "speaker_name": null,
          "side": "left",
          "x": null,
          "y": null,
          "width": null,
          "tail": null
        }
      ]
    }
  ]
}
```

### Position contract

`x`, `y`, `width` on `Bubble` and `x`, `y` on `Sfx`:

| Value | Behaviour |
|-------|-----------|
| `null` | CSS auto-layout. Narration → top of panel. Speech/thought → bottom. SFX → centered at bottom 18%. |
| `float` (pixels) | Pinned — rendered as `position: absolute; left: Xpx; top: Ypx` inside the panel. |

### Theming

`compose/theme.css` is written on first run and is freely editable. Changes take
effect on the next export. For live iteration:

1. Open `compose/html/page_NNN.html` in a browser
2. Edit `compose/theme.css`
3. Hard-refresh the browser tab

Available themes: `default`, `noir`, `manga`, `vintage`, `painted`. Set
`comic_theme` in `config.yaml`, or leave as `auto` to detect from
`style_template` keywords.

---

## Story Bible Format

The Story Bible (`story_bible.json`) is the central artifact. Every downstream
stage reads from it. Edit it after Stage 1 before approving.

```json
{
  "title": "The Gift of the Magi",
  "author": "O. Henry",
  "total_scenes": 8,
  "characters": [
    {
      "id": "char_001",
      "name": "Della",
      "visual_anchor": "Young woman, early 20s, slender build, warm brown eyes, long chestnut hair that falls past her knees, worn grey dress with a frayed collar, bare feet in scuffed leather shoes, delicate hands. Same character, same appearance.",
      "age_range": "early 20s",
      "gender": "female",
      "distinguishing_features": ["unusually long chestnut hair", "frayed collar"],
      "default_outfit": "worn grey dress, scuffed leather shoes",
      "relationships": [{"character_id": "char_002", "relationship": "husband"}],
      "first_appearance_scene": "scene_001"
    }
  ],
  "locations": [
    {
      "id": "loc_001",
      "name": "The Apartment",
      "visual_anchor": "Small furnished flat, dingy wallpaper in faded floral pattern, narrow window overlooking brick wall, wooden letter-box by door, single gas lamp casting warm orange glow, sparse furniture.",
      "mood": "humble"
    }
  ],
  "scenes": [...],
  "narrative_arcs": [...],
  "props": [...]
}
```

**Critical rule:** The `visual_anchor` field must be a camera-ready physical
description — what a camera would see, not personality or backstory. It must end
with `"Same character, same appearance."` and be exactly 60–80 words for
characters, 40–60 words for locations.

---

## Cost Reference

### Per-component costs (approximate)

| Component | Model | Cost |
|-----------|-------|------|
| Global extraction (1 novel) | Gemini 3.1 Pro | ~$0.46 |
| Screenplay adapt (18 scenes) | Gemini 3.1 Pro | ~$0.72 |
| Panel breakdown (18 scenes) | Gemini Flash-Lite | ~$0.09 |
| Image prompts (89 panels) | Gemini Flash-Lite | ~$0.09 |
| **LLM subtotal** | | **~$1.37** |
| Character refs (4 chars × 4 angles) | Gemini image | varies |
| Location plates (3 locations) | Gemini image | varies |
| Panel images (89 panels) | Gemini image | varies |
| **Image subtotal** | | **~$3–10** |
| **Total (short story PoC)** | | **~$5–12** |

### Scale estimates

| Novel size | Panels | LLM cost | Image cost | Total |
|-----------|--------|----------|-----------|-------|
| Short story (10 pages) | ~20 | ~$0.50 | ~$0.60 | ~$1–2 |
| Novella (100 pages) | ~200 | ~$1.50 | ~$6 | ~$8–10 |
| Novel (300 pages) | ~600 | ~$3.00 | ~$18 | ~$21–25 |

---

## Troubleshooting

**Stage fails with rate limit errors**  
Reduce `parallel_batch_size` and `max_concurrent_requests` in `config.yaml`.
The pipeline resumes from where it left off.

**Character drift across panels**  
Ensure reference images were approved after Stage 2. If drift persists,
regenerate character reference sheets with a more detailed `visual_anchor`
description — edit `story_bible.json` directly and rerun Stage 2.

**JSON validation errors from LLM**  
Gemini uses `response_mime_type: "application/json"` to enforce structured
output. If validation fails, the stage retries up to 3 times with exponential
backoff.

**Qdrant connection refused**  
Qdrant is optional and disabled by default. If you enabled it:
`docker start qdrant` or `docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:latest`

**Resume after crash**  
Rerun the pipeline or specific stage via the web UI or API. Each stage checks
`state.json` and skips already-completed items. Failed panels are tracked in
`state.stages.<stage>.items_failed` and are retried automatically on the next run.

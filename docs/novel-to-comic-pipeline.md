# Novel-to-Comic Pipeline

A 9-stage Python/FastAPI/React application that converts a novel
(EPUB, TXT, or PDF) into a graphic novel (PDF/CBZ), using LLMs for story
analysis and image generation models for panel artwork.

**Cost estimate:** varies by LiteLLM gateway routing, image alias pricing, and
reference-image usage. Use `/estimate` and the credits UI for project-specific
stage estimates.

---

## Architecture

```
Novel (EPUB / TXT / PDF)
  │
  ▼ Stage 1 — Extract (configurable text alias)
  │   Full novel → Story Bible JSON
  │   Characters (visual anchors), locations, scenes, narrative arcs, props
  │   ► CHECKPOINT: review story_bible.json before continuing
  │
  ▼ Stage 2 — Style (prompt alias + image alias)
  │   Story Bible → 5 visual style templates + sample images
  │   ► CHECKPOINT: pick an active style before continuing
  │
  │   ── Style Gate: user must select a style before any post-style stage runs ──
  │
  ▼ Stage 3 — Cast (image gen via LiteLLM gateway)
  │   Character reference sheets (4 angles each) + location background plates
  │   ► CHECKPOINT: review refs/ and plates/ before continuing
  │
  ▼ Stage 4 — Adapt (configurable screenplay alias)
  │   Per-scene: prose → observable actions, compressed dialogue (≤35 words/bubble)
  │   Removes interiority; adds SFX annotations
  │
  ▼ Stage 5 — Plan (configurable panel alias)
  │   Screenplay → Layout Plan JSON (planned pages + planned panels)
  │   Assigns panel geometry, page layout, generation modes
  │
  ▼ Stage 6 — Storyboard (deterministic projection)
  │   Layout plan → legacy PanelBreakdown JSON per panel
  │   Shot type, camera angle, character positions, expressions, dialogue
  │
  ▼ Stage 7 — Direct (deterministic prompt spec assembly)
  │   Per-panel: assembles image prompt specs from planned panels:
  │     [Location anchor] + [Character anchor(s)] + [Panel description]
  │   Character visual anchors injected VERBATIM for consistency
  │
  ▼ Stage 8 — Draw (image gen via LiteLLM gateway)
  │   Per-panel: prompt + reference images → panel PNG
  │   ► CHECKPOINT: review generated images before continuing
  │
  ▼ Stage 9 — Compose (deterministic — Playwright + Pillow)
      Panel images + bubble/SFX → HTML → PNG pages → PDF/CBZ export
      Speech bubbles, thought bubbles, narration captions, SFX composited in post
```

### Key Design Principles

| Principle | Implementation |
|-----------|---------------|
| **Character anchors are sacred** | 60–80 word physical description injected verbatim into every image prompt. Never paraphrased. |
| **Text in post** | Speech bubbles composited in Stage 9 — never generated inside images. |
| **Layout plan as planner** | Stage 5 owns page/panel structure; downstream stages project from it. |
| **Decompose relentlessly** | Each LLM call does exactly one thing. No end-to-end generation. |
| **Human checkpoints at boundaries** | Pipeline pauses after `extract`, `style`, `cast`, `direct`, and `draw`. |
| **Style gate enforced** | Backend blocks post-style stages until a style is selected. Frontend reads `style_selected` from status API (sourced from `config.yaml`, never stale). |
| **Resume from failure** | `state.json` tracks every item. Interrupted stages resume where they left off. |

---

## Model Choices

Defaults in `config.py`, overridable in `config.yaml`.

### Text / LLM stages

All text stages route through `novel_to_comic.ai.client` and LiteLLM gateway aliases.
Provider routes live in `litellm/config.yaml`.

| Stage | Default alias (balanced) | Config field |
|-------|--------------------------|-------------|
| Extract (1) | `extract-balanced` | `extraction_model` |
| Adapt (4) | `screenplay-balanced` | `screenplay_model` |
| Plan (5) | `panel-balanced` | `panel_model` |
| Prompt/style/instruction tasks | `prompt-balanced` | `prompt_model` |

Aliases are intent + preset (e.g. `extract-fast`, `screenplay-quality`).
Set `quality_preset: fast | balanced | quality` to switch all five intents at once.
`dev_mode` forces the `fast` preset regardless.

### Image generation

Configured via gateway aliases in `config.yaml`:

```yaml
image_model: "image-balanced"
fallback_image_model: "image-fast"
```

Available image aliases: `image-fast`, `image-balanced`, `image-quality`, `image-reve`.
The LiteLLM proxy resolves them to provider/model routes. `image-balanced` routes
to Gemini Pro Image. `image-quality` and `image-reve` both route to Reve
(`REVE_ALIASES`). Draw selects refs via `_reve_refs()` for Reve: up to 3 subject
crops plus continuity/prop/style/location up to 4 total. GPT Image 2 is no longer
a default gateway alias (`GPT_IMAGE_2_ALIASES` is empty).

---

## Installation

**Requirements:** Python 3.12+

```bash
git clone <repo>
cd canary/novel_to_comic

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e .

# One-time: install Playwright Chromium browser (required for Stage 9 — HTML → PNG rendering)
playwright install chromium
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
echo "LITELLM_BASE_URL=http://localhost:4000" >> .env
echo "LITELLM_API_KEY=sk-local-canary" >> .env
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
- 9 backend stages mapped into 8 user-facing rooms with per-artifact viewers
  and editors
- Pipeline run/approve/reset controls
- Live SSE streaming of stage progress
- Stage 9 page editor with bubble/SFX editing, theme switching, and export

### Run stages via API

```bash
# Run a specific stage
curl -X POST "http://localhost:8000/api/projects/my-novel/run?stage=draw"

# Rerun a stage from scratch and clear downstream outputs
curl -X POST "http://localhost:8000/api/projects/my-novel/run?stage=draw&rerun=true"

# Retry only failed draw panels
curl -X POST "http://localhost:8000/api/projects/my-novel/run?stage=draw&retry_failed=true"

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
├── samples/                 # Style suggestions and generated samples
│   ├── style_suggestions.json
│   └── style_N.png
├── refs/                    # Character and prop reference images
│   ├── char_NNN/
│   │   ├── sheet.png
│   │   ├── front.png
│   │   ├── three_quarter.png
│   │   ├── profile.png
│   │   ├── gesture.png
│   │   ├── sheet.png.meta.json
│   │   └── instructions.jsonl
│   └── props/
│       └── prop_NNN/
│           ├── ref.png
│           ├── ref.png.meta.json
│           └── instructions.jsonl
├── plates/                  # Location background plates (loc_NNN.png …)
├── screenplays/             # Per-scene screenplay JSON
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
├── compose/                 # Stage 9 output
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

## Stage 9 Editing (compose)

Stage 9 produces `compose/pages/page_NNN.json` — the **editing surface** for every
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
          "tail_x": null,
          "tail_y": null,
          "tail_direction": "auto"
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

Pinned speech bubbles can also set `tail_x` and `tail_y` to draw an SVG tail
toward a panel-relative target point. Bubbles without `tail_x`/`tail_y` use CSS
tails controlled by `tail_direction`.

### Compose web editor

The Compose room edits the same `ComicPage` JSON through four modes:

- **Script:** Review all page lettering, translate page bubbles, and jump from a
  line of dialogue to the matching bubble in Layout mode.
- **Layout:** Place bubbles/SFX on the page, edit panel image offsets, use the
  floating or fixed inspector, apply page layout presets, and make
  planner-backed structural overrides.
- **Style:** Generate lettering variables from the active art style, apply
  bubble presets, manage character voice presets, and translate bubbles
  project-wide.
- **Preview:** Review two-page spreads, zoom/pan the rendered page iframes, and
  export PDF or CBZ.

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
      "visual_anchor": "1woman, adult female, early 20s, slender build, warm brown eyes, very long chestnut hair, worn grey dress, frayed collar, scuffed leather shoes, delicate hands",
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

**Critical rule:** The `visual_anchor` field must be camera-ready visual evidence
only — what a camera would see, not personality or backstory. Character anchors
use strict comma-separated Danbooru-style tags with no situational state such as
wet, dirty, shivering, injured, or covered in blood.

---

## Cost Reference

Costs are tracked automatically. Each API call returns an `ApiResult` with a
`UsageRecord`; the pipeline accumulates real costs into `state.json` via
`usage_log` and `cost_usd`. Before a stage runs, an estimate is saved to
`estimated_cost_usd`. Pricing comes from `litellm_model_prices.cached.json`
plus `litellm_pricing_overrides.yaml`; `audit_pricing()` validates configured
gateway aliases at startup.

### Per-component cost drivers

| Component | Model/alias | What drives cost |
|-----------|-------------|------------------|
| Global extraction | `extract-balanced` | novel length and output Story Bible size |
| Style suggestions | `prompt-balanced` | Story Bible size and suggestion count |
| Style samples | `image-balanced` | sample count and image-model route |
| Character refs | `image-balanced` | character count and reference conditioning |
| Prop refs | `image-balanced` | recurring/plot-central prop count and reference conditioning |
| Location plates | `image-balanced` | location count |
| Screenplay adapt | `screenplay-balanced` | scene count and prose length |
| Layout planning | `panel-balanced` | scene count and beat count |
| Prompt specs | deterministic | no model cost |
| Panel images | `image-balanced` | panel count, provider-specific reference image count, image dimensions, and provider pricing |

### Scale estimates

Use the stage estimate endpoints and credits UI for current numbers. The old
fixed dollar tables were removed because gateway aliases can route to different
providers per deployment.

---

## Troubleshooting

**Stage fails with rate limit errors**  
Reduce `parallel_batch_size` and `max_concurrent_requests` in `config.yaml`.
The pipeline resumes from where it left off.

**Character drift across panels**  
Ensure reference images were approved after Stage 3 (`cast`). If drift persists,
regenerate character reference sheets with a more detailed `visual_anchor`
description — edit `story_bible.json` directly and rerun Stage 3.

**JSON validation errors from LLM**
Gemini uses `response_mime_type: "application/json"` to enforce structured
output. Other providers use similar constraints. If validation fails,
the stage retries up to 3 times with exponential backoff.

**Resume after crash**
Rerun the pipeline or specific stage via the web UI or API. Each stage checks
`state.json` and skips already-completed items. Failed panels are tracked in
`state.stages.<stage>.items_failed` and are retried automatically on the next run.

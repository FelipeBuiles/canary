# Novel-to-Comic Pipeline

A 7-stage CLI pipeline that converts a novel (EPUB or TXT) into a graphic novel (PDF/CBZ), using LLMs for story analysis and FLUX.2 Pro for image generation.

**Cost estimate:** ~$25–35 for a 300-page novel (600 panels) at standard quality.  
**PoC cost:** ~$2–5 for a 10-page short story (15–20 panels).

---

## Architecture

```
Novel (EPUB/TXT)
  │
  ▼ Stage 1 — Global Extraction          [Gemini 3.1 Pro, 1M context]
  │   Full novel → Story Bible JSON
  │   Characters (visual anchors), locations, scenes, narrative arcs
  │   ► HUMAN CHECKPOINT: review Story Bible
  │
  ▼ Stage 2 — RAG Index + Reference Images  [Google Embeddings + FLUX.2 Pro]
  │   Scene text → Qdrant vector index (hybrid search)
  │   Story Bible characters → reference sheets (4 views each)
  │   Story Bible locations → background plates
  │   ► HUMAN CHECKPOINT: review character designs
  │
  ▼ Stage 3 — Screenplay Adaptation      [Claude Sonnet 4.6]
  │   Per-scene: prose → observable actions, compressed dialogue (≤35 words/bubble)
  │   Removes interiority; adds SFX annotations
  │
  ▼ Stage 4 — Panel Breakdown            [Gemini 2.5 Flash-Lite]
  │   Per-scene: screenplay → 3–8 panel JSON objects
  │   Shot type, camera angle, character positions, expressions, dialogue
  │
  ▼ Stage 5 — Image Prompt Assembly      [Gemini 2.5 Flash-Lite]
  │   Per-panel: assembles prompt from 4 components:
  │     [Style template] + [Location anchor] + [Character anchor(s)] + [Scene direction]
  │   Character visual anchors injected VERBATIM for consistency
  │
  ▼ Stage 6 — Image Generation           [FLUX.2 Pro via Together AI, $0.03/image]
  │   Per-panel: prompt + up to 8 reference images → 1024×1344px PNG
  │   Batched async generation with rate limiting and retry
  │   ► HUMAN CHECKPOINT: review generated panels
  │
  ▼ Stage 7 — Assembly + Export          [HTML/CSS + Playwright + Pillow]
      Panel images + PanelBreakdown JSON → ComicPage JSON (editing surface)
      Speech bubbles, thought bubbles, narration captions, SFX composited in post
      HTML/CSS rendered by headless Chromium → PNG pages
      Export: PDF (print), CBZ (comic reader)
```

### Key Design Principles

| Principle | Implementation |
|---|---|
| **Character anchors are sacred** | 60–80 word physical description injected verbatim into every image prompt. Never paraphrased. |
| **Text in post** | Speech bubbles composited by Pillow in Stage 7 — never generated inside images. |
| **Edit, don't regenerate** | Fix panels from the original character reference image, not from a previous failed panel. |
| **Decompose relentlessly** | Each LLM call does exactly one thing. No end-to-end generation. |
| **Human checkpoints at boundaries** | Pipeline pauses after extraction, character design, and image generation for review. |
| **Resume from failure** | `state.json` tracks every item. Any interrupted stage resumes where it left off. |

---

## Model Choices

| Stage | Model | Why |
|---|---|---|
| Global extraction | `gemini-3.1-pro-preview` | 1M context window fits a full novel in one pass |
| Screenplay | `claude-sonnet-4-6-20250514` | Best creative writing, strict instruction following |
| Panel breakdown | `gemini-3.1-flash-lite-preview` | Structured JSON, fast and cheap |
| Image prompts | `gemini-3.1-flash-lite-preview` | Template assembly, Flash-Lite sufficient |
| Embeddings | `gemini-embedding-2-preview` (Google) | 3072 dims, strong semantic retrieval |
| Image generation | `gemini-3-pro-image-preview` (default) | Native Gemini 3, no per-image cost |
| Image generation (fallback) | `gemini-3.1-flash-image-preview` | Triggered automatically on 429 rate limits |
| Vector store | Qdrant | Hybrid search (dense + BM25), excellent metadata filtering |

Image generation also supports `imagen-4-*` (Vertex AI) and FLUX.2 Pro via Together AI (`black-forest-labs/FLUX.2-pro`, $0.03/image). Switch via `image_model` in `config.yaml`. See `clients/flux.py` for routing logic.

---

## Installation

**Requirements:** Python 3.12+, Docker (for Qdrant)

```bash
git clone <repo>
cd novel_to_comic

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -e .

# Install Playwright browser (required for Stage 7 — HTML → PNG rendering)
playwright install chromium
```

Start Qdrant (required for Stage 2):

```bash
docker run -d --name qdrant \
  -p 6333:6333 \
  -v ./qdrant_data:/qdrant/storage \
  qdrant/qdrant:latest
```

---

## Setup

### 1. Create a project

```bash
pipeline init --input /path/to/novel.epub --name my-novel --output ./projects
```

This creates `./projects/my-novel/` with the full directory structure and a default `config.yaml`.

### 2. Add API keys

Edit `./projects/my-novel/config.yaml`:

```yaml
gemini_api_key: "..."        # Required for stages 1, 4, 5
anthropic_api_key: "..."     # Required for stage 3
together_api_key: "..."      # Required for stage 6 (image generation)
openai_api_key: ""           # Optional — only if switching to OpenAI embeddings

# Model overrides (optional — defaults shown)
extraction_model: "gemini-3.1-pro-preview"
screenplay_model: "claude-sonnet-4-6-20250514"
panel_model: "gemini-2.5-flash-lite"
prompt_model: "gemini-2.5-flash-lite"
embedding_model: "text-embedding-005"
image_model: "black-forest-labs/FLUX.2-pro"

# Image settings
image_width: 1024
image_height: 1344
image_steps: 28
flux_guidance_scale: 3.5

# Style applied to every generated image
style_template: |
  Bold graphic novel style, cel-shaded coloring, high contrast shadows,
  limited color palette, thick ink outlines, dynamic composition,
  professional comic book art quality, detailed backgrounds.

# Pipeline settings
max_panels_per_scene: 8
max_words_per_bubble: 35
parallel_batch_size: 5
max_concurrent_requests: 5
cost_limit_usd: 50.0          # Optional hard cap
```

---

## Usage

### Run the full pipeline

```bash
pipeline run all --project ./projects/my-novel
```

The pipeline runs stages sequentially and **pauses at each checkpoint** (stages 1, 2, 6) for human review. After reviewing, approve and continue:

```bash
# Review story_bible.json, then:
pipeline approve --project ./projects/my-novel --stage extract
pipeline run all --project ./projects/my-novel

# Review refs/ directory (character images), then:
pipeline approve --project ./projects/my-novel --stage index
pipeline run all --project ./projects/my-novel

# Review images/ directory (generated panels), then:
pipeline approve --project ./projects/my-novel --stage generate
pipeline run all --project ./projects/my-novel
```

### Run individual stages

```bash
pipeline run extract    --project ./projects/my-novel
pipeline run index      --project ./projects/my-novel
pipeline run screenplay --project ./projects/my-novel
pipeline run panels     --project ./projects/my-novel
pipeline run prompts    --project ./projects/my-novel
pipeline run generate   --project ./projects/my-novel
pipeline run assemble   --project ./projects/my-novel
```

### Targeted runs

```bash
# Run a single scene through stages 3–6
pipeline run screenplay --project ./projects/my-novel --scene scene_012
pipeline run panels     --project ./projects/my-novel --scene scene_012
pipeline run prompts    --project ./projects/my-novel --scene scene_012
pipeline run generate   --project ./projects/my-novel --scene scene_012

# Retry only failed image generation
pipeline run generate --project ./projects/my-novel --retry-failed

# Export in specific formats
pipeline run assemble --project ./projects/my-novel --format pdf,cbz
pipeline export       --project ./projects/my-novel --format pdf
```

### Check status

```bash
pipeline status --project ./projects/my-novel
```

```
        Pipeline Status: my-novel
┏━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━┓
┃ Stage      ┃ Status          ┃ Progress ┃ Cost  ┃
┡━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━┩
│ extract    │ complete        │ 1/1      │ $0.46 │
│ index      │ complete        │ 24/24    │ $1.20 │
│ screenplay │ complete        │ 18/18    │ $0.72 │
│ panels     │ complete        │ 18/18    │ $0.09 │
│ prompts    │ complete        │ 89/89    │ $0.09 │
│ generate   │ awaiting_review │ 89/89    │ $2.67 │
│ assemble   │ pending         │          │       │
└────────────┴─────────────────┴──────────┴───────┘

Total cost: $5.23
```

---

## Project Directory Structure

```
my-novel/
├── config.yaml           # API keys + pipeline config
├── state.json            # Stage progress, costs, failed items
├── story_bible.json      # Central artifact — ALL downstream stages read this
├── input/
│   └── novel.epub
├── scenes/               # Extracted scene text files (scene_001.txt …)
├── qdrant_data/          # Qdrant persistent storage (local Docker)
├── refs/                 # Character reference sheets
│   ├── char_001/
│   │   ├── front.png
│   │   ├── three_quarter.png
│   │   ├── side.png
│   │   └── action.png
│   └── char_002/
├── plates/               # Location background plates (loc_001.png …)
├── screenplays/          # Per-scene screenplay JSON (scene_001.json …)
├── panels/               # Per-panel breakdown JSON
│   └── scene_001/
│       ├── panel_001.json
│       └── panel_002.json
├── prompts/              # Per-panel image prompts (assembled)
│   └── scene_001/
│       └── panel_001.json
├── images/               # Generated panel images
│   └── scene_001/
│       └── panel_001.png
├── assembly/
│   ├── theme.css         # Editable CSS variables — run `pipeline export` to apply changes
│   ├── pages/            # ComicPage JSON (editing surface) + rendered PNGs
│   │   ├── page_001.json
│   │   └── page_001.png
│   └── html/             # HTML previews — open in browser, edit theme.css, hard-refresh
│       └── page_001.html
└── exports/
    ├── comic.pdf
    └── comic.cbz
```

---

## Assembly & Bubble Editing

Stage 7 produces `assembly/pages/page_NNN.json` — the **editing surface** for every comic page. Edit these files directly (or via the future web dashboard) and run `pipeline export` to re-render without re-running earlier stages.

### ComicPage JSON structure

```json
{
  "page_number": 1,
  "theme": "noir",
  "layout": "4",
  "panels": [
    {
      "id": "scene_001-003",
      "image_path": "images/scene_001/panel_003.png",
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
          "width": null
        }
      ]
    }
  ]
}
```

### Position contract

`x`, `y`, `width` on a `Bubble` and `x`, `y` on an `Sfx` follow the same rule:

| Value | Behaviour |
|---|---|
| `null` | CSS auto-layout. Narration → top of panel. Speech/thought → bottom of panel (flex-stacked). SFX → centered at bottom 18%. |
| `float` (pixels) | Pinned — rendered as `position: absolute; left: Xpx; top: Ypx` inside the panel. Set by the web editor drag-and-drop. |

### Editing bubbles manually

Open `assembly/pages/page_NNN.json`, change any field, then re-export:

```bash
# Re-render all pages from existing JSON (does not rebuild from panel data)
pipeline export --project ./projects/my-novel

# Force a full rebuild from panel images + breakdown JSON
pipeline export --project ./projects/my-novel --rebuild
```

To pin a bubble to a specific position, set `x` and `y` (pixels from the panel's top-left corner). Set `width` to constrain the bubble width.

### Theming

`assembly/theme.css` is written on first run and is freely editable. It contains a full list of CSS variables with their defaults. Changes take effect on the next `pipeline export`. For live iteration:

1. Open `assembly/html/page_NNN.html` in a browser
2. Edit `theme.css`
3. Hard-refresh the browser tab

Available themes: `default`, `noir`, `manga`, `vintage`, `painted`. Set `comic_theme` in `config.yaml`, or leave it as `auto` to detect from `style_template` keywords.

---

## Story Bible Format

The Story Bible (`story_bible.json`) is the central artifact. Every downstream stage reads from it. You can and should edit it manually after Stage 1 before approving.

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
  "narrative_arcs": [...]
}
```

**Critical rule:** The `visual_anchor` field must be a camera-ready physical description — what a camera would see, not personality or backstory. It must end with `"Same character, same appearance."` and be exactly 60–80 words for characters, 40–60 words for locations.

---

## Cost Reference

### Per-component costs

| Component | Model | Cost |
|---|---|---|
| Global extraction | Gemini 3.1 Pro | ~$0.46/novel |
| Embeddings | text-embedding-005 | ~$0.001/novel |
| Screenplay (18 scenes) | Claude Sonnet 4.6 | ~$0.72 |
| Panel breakdown | Gemini 2.5 Flash-Lite | ~$0.09 |
| Image prompts | Gemini 2.5 Flash-Lite | ~$0.09 |
| **LLM subtotal** | | **~$1.37** |
| Character refs (4 chars × 4 views) | FLUX.2 Pro | $0.48 |
| Location plates (3 locations) | FLUX.2 Pro | $0.09 |
| Panel images (89 panels) | FLUX.2 Pro | $2.67 |
| **Image subtotal** | | **~$3.24** |
| **Total (short story PoC)** | | **~$4.61** |

### Scale estimates

| Novel size | Panels | LLM cost | Image cost | Total |
|---|---|---|---|---|
| Short story (10 pages) | ~20 | ~$0.50 | ~$0.60 | **~$1–2** |
| Novella (100 pages) | ~200 | ~$1.50 | ~$6.00 | **~$8–10** |
| Novel (300 pages) | ~600 | ~$3.00 | ~$18.00 | **~$21–25** |

---

## Troubleshooting

**Stage fails with rate limit errors**  
Reduce `parallel_batch_size` and `max_concurrent_requests` in `config.yaml`. The pipeline will resume from where it left off.

**Character drift across panels**  
Ensure reference images were approved and are good quality after Stage 2. If drift persists, consider regenerating character reference sheets with a more detailed `visual_anchor` description — edit `story_bible.json` directly and rerun Stage 2.

**JSON validation errors from LLM**  
Gemini uses `response_mime_type: "application/json"` to enforce structured output. If validation fails anyway, the stage retries up to 3 times with exponential backoff. If it keeps failing, inspect the model's raw output by running the stage in verbose mode.

**Qdrant connection refused**  
Start Docker and run: `docker start qdrant`  
Or spin up fresh: `docker run -d --name qdrant -p 6333:6333 qdrant/qdrant:latest`

**Resume after crash**  
Just rerun the same command. Each stage checks `state.json` and skips already-completed items. Individual failed panels are tracked in `state.stages.generate.items_failed` and can be retried with `--retry-failed`.

```
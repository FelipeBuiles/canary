# Novel-to-Comic Pipeline: Build Plan

**Purpose**: This document is a complete implementation spec. It contains everything an engineer (or AI agent) needs to build this pipeline from scratch in a single session, without access to any prior conversation. Read this entire document before writing any code.

**Date**: April 2026
**Language**: Python 3.12+
**Scope**: Phase 1 PoC — a CLI tool that converts a novel (EPUB/TXT) into comic pages (PNG/PDF), with human review checkpoints.

---

## 1. What We're Building

A 7-stage pipeline that takes a novel as input and produces a graphic novel as output. Each stage is a pure function from files to files. All intermediate artifacts live in a single project directory. A `state.json` file tracks progress, enabling resume-from-failure and selective re-runs.

```
Novel (EPUB/TXT)
  → [1] Story Bible JSON (characters, locations, scenes)
  → [2] RAG index + character reference images + location plates
  → [3] Per-scene screenplays
  → [4] Per-panel breakdown JSON
  → [5] Per-panel image prompts
  → [6] Panel images (FLUX.2 Pro API)
  → [7] Assembled comic pages + PDF/CBZ export
```

The pipeline costs ~$25–35 for a 300-page novel at standard quality (600 panels via FLUX.2 Pro). LLM processing is ~$2.72; image generation is the dominant cost.

---

## 2. Critical Design Decisions (Non-Negotiable)

These are hard-won lessons from research and community experience. Do not deviate.

1. **Character visual anchors are sacred.** Every character gets a fixed ~60–80 word physical description in the Story Bible. This exact text is injected verbatim into every image prompt for that character. Never paraphrase, never summarize, never omit. This is the #1 consistency technique.

2. **Text is never generated inside images.** Speech bubbles, captions, and all text are composited programmatically in the assembly stage (stage 7). Image prompts must always end with: `"No text. No speech bubbles. No captions. No lettering. Single panel only."`

3. **Edit, don't regenerate.** When a panel needs fixing, edit from the original character reference image, not from the failed panel. Iterating on bad outputs causes cumulative drift.

4. **Decompose relentlessly.** Each LLM call does exactly one thing. Never ask a model to go from novel text to image prompt in one shot. The 5-stage LLM decomposition (extract → screenplay → panels → prompts) is validated by EMNLP 2025 research showing 75% win rate over end-to-end approaches.

5. **FLUX.2 uses positive-only prompting.** No negative prompts. Describe what you want, not what to avoid. Guidance scale 3.5–4.5.

6. **Human checkpoints at stage boundaries.** The pipeline pauses for approval after: stage 1 (Story Bible), stage 2 (character designs), and stage 6 (generated panels). These are not optional — skipping them produces unusable output.

---

## 3. Project Structure

```
novel_to_comic/
├── pyproject.toml
├── README.md
├── src/
│   └── novel_to_comic/
│       ├── __init__.py
│       ├── cli.py                 # Click CLI entry point
│       ├── config.py              # Pydantic settings from config.yaml
│       ├── state.py               # State machine: read/write state.json
│       ├── stages/
│       │   ├── __init__.py
│       │   ├── s1_extract.py      # Novel → Story Bible
│       │   ├── s2_index.py        # RAG index + character refs + location plates
│       │   ├── s3_screenplay.py   # Scene → screenplay
│       │   ├── s4_panels.py       # Screenplay → panel JSON
│       │   ├── s5_prompts.py      # Panel JSON → image prompts
│       │   ├── s6_generate.py     # Image prompts → panel images
│       │   └── s7_assemble.py     # Panel images → comic pages + export
│       ├── models/
│       │   ├── __init__.py
│       │   ├── story_bible.py     # Pydantic models for Story Bible
│       │   ├── panel.py           # Pydantic models for panel breakdown
│       │   └── prompt.py          # Pydantic models for image prompts
│       ├── clients/
│       │   ├── __init__.py
│       │   ├── gemini.py          # Google Gemini API wrapper
│       │   ├── claude.py          # Anthropic Claude API wrapper
│       │   ├── flux.py            # Together AI / BFL FLUX.2 wrapper
│       │   └── embeddings.py      # OpenAI embeddings wrapper
│       ├── rag/
│       │   ├── __init__.py
│       │   ├── chunker.py         # Scene-boundary chunking
│       │   └── store.py           # Qdrant vector store operations
│       └── prompts/               # System prompt templates (plain text)
│           ├── extraction.txt
│           ├── screenplay.txt
│           ├── panel_breakdown.txt
│           └── image_prompt.txt
└── tests/
    └── ...
```

### Runtime Project Directory (created per novel)

```
my-novel-project/
├── config.yaml               # Copy of pipeline config with project-specific overrides
├── state.json                 # Pipeline state tracker
├── input/
│   └── novel.epub             # Source material (user provides)
├── story_bible.json           # Central artifact — ALL downstream stages read this
├── scenes/
│   ├── scene_001.txt          # Extracted scene text
│   ├── scene_002.txt
│   └── ...
├── qdrant_data/               # Qdrant persistent storage
├── refs/                      # Character reference sheets
│   ├── char_001/
│   │   ├── front.png
│   │   ├── three_quarter.png
│   │   ├── side.png
│   │   └── action.png
│   └── char_002/
├── plates/                    # Location background plates
│   ├── loc_001.png
│   └── loc_002.png
├── screenplays/
│   ├── scene_001.json
│   └── ...
├── panels/
│   ├── scene_001/
│   │   ├── panel_001.json
│   │   ├── panel_002.json
│   │   └── ...
│   └── ...
├── prompts/
│   ├── scene_001/
│   │   ├── panel_001.json
│   │   └── ...
│   └── ...
├── images/
│   ├── scene_001/
│   │   ├── panel_001.png
│   │   ├── panel_001_upscaled.png
│   │   └── ...
│   └── ...
├── pages/
│   ├── page_001.png
│   └── ...
└── exports/
    ├── comic.pdf
    ├── comic.cbz
    └── comic.epub
```

---

## 4. Data Models (Pydantic)

### 4.1 Config (`config.yaml`)

```yaml
# API Keys
gemini_api_key: "..."
anthropic_api_key: "..."
together_api_key: "..."        # For FLUX.2 Pro
openai_api_key: "..."          # For embeddings only

# Model choices
extraction_model: "gemini-2.5-pro"
screenplay_model: "claude-sonnet-4-6-20250514"
panel_model: "gemini-2.5-flash"
prompt_model: "gemini-2.5-flash"
embedding_model: "text-embedding-3-small"
image_model: "black-forest-labs/FLUX.2-pro"

# Image generation
image_width: 1024
image_height: 1344              # 3:4 aspect ratio, portrait panels
image_steps: 28
flux_guidance_scale: 3.5

# Style template (injected into every image prompt)
style_template: |
  Bold graphic novel style, cel-shaded coloring, high contrast shadows,
  limited color palette, thick ink outlines, dynamic composition,
  professional comic book art quality, detailed backgrounds.

# Pipeline settings
max_panels_per_scene: 8
max_words_per_bubble: 35
parallel_batch_size: 5          # How many scenes to process in parallel
qdrant_host: "localhost"
qdrant_port: 6333
```

### 4.2 Story Bible (`story_bible.json`)

```python
from pydantic import BaseModel
from typing import Optional

class CharacterRelationship(BaseModel):
    character_id: str
    relationship: str           # "partner", "antagonist", "sibling", etc.

class Character(BaseModel):
    id: str                     # "char_001"
    name: str                   # "Elena Vasquez"
    visual_anchor: str          # EXACTLY 60-80 words. Physical description ONLY.
                                # No personality, no backstory. Just what a camera sees.
                                # Must end with "Same character, same appearance."
    age_range: str              # "early 30s"
    gender: str
    distinguishing_features: list[str]  # ["jagged scar on left cheek", "undercut haircut"]
    default_outfit: str         # What they typically wear
    relationships: list[CharacterRelationship]
    first_appearance_scene: str # "scene_001"

class Location(BaseModel):
    id: str                     # "loc_001"
    name: str                   # "The Bunker"
    visual_anchor: str          # 40-60 words. What the camera sees. Lighting, colors, key objects.
    time_of_day: Optional[str]  # "night", "dawn", etc.
    mood: str                   # "tense", "warm", "desolate"

class Scene(BaseModel):
    id: str                     # "scene_001"
    chapter: int
    title: str                  # Brief scene title
    location_id: str            # References Location.id
    character_ids: list[str]    # Characters present in scene
    summary: str                # 2-3 sentence summary
    scene_type: str             # "action", "dialogue", "emotional", "transition"
    narrative_beat: str         # "inciting_incident", "climax", "resolution", etc.
    source_start_char: int      # Character offset in novel text
    source_end_char: int

class NarrativeArc(BaseModel):
    act: int                    # 1, 2, 3
    title: str
    scenes: list[str]           # Scene IDs in this act
    turning_point: Optional[str]

class StoryBible(BaseModel):
    title: str
    author: str
    total_scenes: int
    characters: list[Character]
    locations: list[Location]
    scenes: list[Scene]
    narrative_arcs: list[NarrativeArc]
    style_notes: Optional[str]  # Any genre-specific visual direction
```

### 4.3 Panel Breakdown

```python
class PanelBreakdown(BaseModel):
    scene_id: str
    panel_number: int           # 1-indexed within scene
    shot_type: str              # "close-up", "medium", "wide", "extreme-wide", "over-shoulder"
    camera_angle: str           # "eye-level", "low-angle", "high-angle", "dutch-angle", "bird-eye"
    characters_present: list[str]  # Character IDs
    character_actions: dict[str, str]   # char_id -> "drawing sword", "looking away"
    character_expressions: dict[str, str]  # char_id -> "determined", "shocked"
    character_positions: dict[str, str]   # char_id -> "left foreground", "center", "right background"
    background_description: str  # What's visible behind characters
    lighting: str               # "harsh overhead", "warm sunset", "dim fluorescent"
    mood: str                   # "tense", "hopeful", "chaotic"
    dialogue: list[dict]        # [{"character_id": "...", "text": "...", "type": "speech|thought|narration"}]
    sfx: Optional[str]          # "BOOM", "CRACK", etc.
    transition_note: Optional[str]  # "smash cut", "fade", for assembly hints
```

### 4.4 Image Prompt

```python
class ImagePrompt(BaseModel):
    scene_id: str
    panel_number: int
    full_prompt: str            # The complete assembled prompt string
    reference_image_paths: list[str]  # Paths to character ref images to send as multi-ref
    negative_prompt: None       # ALWAYS None. FLUX.2 does not support negative prompts.
    width: int
    height: int
    steps: int
    guidance_scale: float
```

### 4.5 Pipeline State (`state.json`)

```python
from enum import Enum
from datetime import datetime

class StageStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"  # Paused at human checkpoint
    COMPLETE = "complete"
    FAILED = "failed"

class StageState(BaseModel):
    status: StageStatus
    started_at: Optional[datetime]
    finished_at: Optional[datetime]
    items_done: int = 0
    items_total: int = 0
    items_failed: list[str] = []  # IDs of failed items for retry
    approved: Optional[bool] = None  # For checkpoint stages
    cost_usd: float = 0.0
    error: Optional[str] = None

class PipelineState(BaseModel):
    project_name: str
    novel_path: str
    created_at: datetime
    stages: dict[str, StageState]    # Keys: "extract", "index", "screenplay", "panels", "prompts", "generate", "assemble"
    total_cost_usd: float = 0.0
```

---

## 5. Stage-by-Stage Implementation Specs

### Stage 1: Global Extraction

**Model**: Gemini 2.5 Pro (1M context window)
**Input**: Entire novel text (up to ~120K tokens for a 300-page novel)
**Output**: `story_bible.json`
**Cost**: ~$0.23 per novel
**Checkpoint**: Yes — user must review and approve the Story Bible before proceeding

**How it works**:
1. Read the novel file. For EPUB, use `ebooklib` to extract text. For TXT/PDF, read directly.
2. Make ONE long-context API call to Gemini 2.5 Pro with the full novel text + the extraction system prompt.
3. The system prompt instructs the model to output structured JSON matching the `StoryBible` schema.
4. Validate the response against the Pydantic model. If validation fails, retry with error feedback.
5. Write `story_bible.json` and individual scene text files to `scenes/`.

**System prompt key instructions** (for `prompts/extraction.txt`):
```
You are a story analyst extracting structured data from a novel for comic adaptation.

Given the complete text of a novel, extract:

1. CHARACTER REGISTRY
   For each named character who appears in 2+ scenes:
   - id: char_NNN (sequential)
   - name: full name as used in the novel
   - visual_anchor: EXACTLY 60-80 words describing ONLY physical appearance.
     What would a camera see? Face shape, hair, eyes, skin, build, scars, 
     distinctive features, typical clothing. NO personality, NO backstory.
     End with: "Same character, same appearance."
   - age_range, gender, distinguishing_features, default_outfit
   - relationships to other characters
   - first_appearance_scene

2. LOCATION REGISTRY
   For each distinct setting:
   - id: loc_NNN
   - visual_anchor: 40-60 words. Physical environment only.
     Architecture, lighting, colors, key objects, atmosphere.
   - time_of_day, mood

3. SCENE LIST
   Segment the novel into discrete scenes. A new scene starts when:
   - Location changes
   - Significant time passes (hours+)
   - POV character changes
   For each scene: id, chapter, location_id, character_ids, summary (2-3 sentences),
   scene_type (action/dialogue/emotional/transition), narrative_beat.

4. NARRATIVE ARCS
   Divide scenes into 3-act structure with turning points.

Output valid JSON matching this exact schema: [include StoryBible schema]

CRITICAL RULES:
- Visual anchors must be camera-ready descriptions. "Kind and brave" is WRONG.
  "Tall woman, early 30s, sharp angular face, short black hair undercut" is RIGHT.
- Every character's visual_anchor must end with "Same character, same appearance."
- Scene boundaries should produce 3-8 panels each when converted to comics.
  If a scene is too long, split it. If too short, merge with adjacent.
- Target 30-60 total scenes for a standard novel.
```

**Error handling**:
- If the novel exceeds Gemini's context window, truncate to first 800K tokens and note the cutoff.
- If JSON parsing fails, extract the JSON from markdown code fences and retry parsing.
- If schema validation fails, send the validation errors back to the model with the original output and ask it to fix only the errors.

---

### Stage 2: RAG Index + Character Design

**Models**: text-embedding-3-small (embeddings), FLUX.2 Pro (character refs)
**Input**: `story_bible.json`, `scenes/` directory
**Output**: Qdrant index, `refs/` directory, `plates/` directory
**Cost**: ~$0.002 (embeddings) + ~$0.50–2.00 (reference images)
**Checkpoint**: Yes — user must approve character reference sheets

**Part A: RAG Index Construction**
1. Read each scene file from `scenes/`.
2. Chunk each scene at paragraph boundaries, targeting 400-800 tokens per chunk. Preserve sentence boundaries — never split mid-sentence.
3. Each chunk gets metadata: `scene_id`, `chapter`, `character_ids`, `location_id`.
4. Embed all chunks with `text-embedding-3-small`.
5. Store in Qdrant with hybrid search enabled (dense vectors + BM25 for keyword matching).

**Qdrant setup** (Docker):
```bash
docker run -d --name qdrant -p 6333:6333 -v ./qdrant_data:/qdrant/storage qdrant/qdrant:latest
```

**Collection config**:
```python
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PayloadSchemaType

client = QdrantClient(host="localhost", port=6333)
client.create_collection(
    collection_name="novel_scenes",
    vectors_config=VectorParams(size=1536, distance=Distance.COSINE),
)
```

**Part B: Character Reference Generation**
For each character in the Story Bible:
1. Construct a prompt: `[STYLE TEMPLATE] + [CHARACTER VISUAL ANCHOR] + "Character reference sheet, neutral standing pose, front view, 3/4 view, side view, white background, clean line art, full body visible. No text. No speech bubbles."`
2. Call FLUX.2 Pro via Together AI. Generate 4 images per character:
   - Front view (neutral pose)
   - 3/4 view
   - Side view
   - Action pose (character-appropriate)
3. Save to `refs/{char_id}/front.png`, etc.

**Part C: Location Plate Generation**
For each location in the Story Bible:
1. Construct a prompt: `[STYLE TEMPLATE] + [LOCATION VISUAL ANCHOR] + "Wide establishing shot, no characters present, detailed background, cinematic composition. No text."`
2. Generate 1 image per location.
3. Save to `plates/{loc_id}.png`.

**FLUX.2 Pro API call via Together AI**:
```python
from together import Together

client = Together(api_key=config.together_api_key)

response = client.images.generate(
    model="black-forest-labs/FLUX.2-pro",
    prompt=prompt_text,
    width=1024,
    height=1344,
    steps=28,
    n=1,
    response_format="b64_json",
    # For multi-reference (character consistency), pass reference images:
    # image_url="data:image/png;base64,{base64_encoded_ref_image}"
)
```

---

### Stage 3: Screenplay Adaptation

**Model**: Claude Sonnet 4.6
**Input**: `story_bible.json`, scene text (via RAG retrieval)
**Output**: `screenplays/{scene_id}.json`
**Cost**: ~$1.81 for entire novel
**Checkpoint**: No

**For each scene**:
1. Retrieve the scene text from the RAG index (query: scene summary, filter by scene_id).
2. Also retrieve the relevant character visual anchors and location description from the Story Bible.
3. Call Claude Sonnet 4.6 with the screenplay system prompt.

**System prompt** (for `prompts/screenplay.txt`):
```
You are a screenplay adapter converting novel scenes to comic-ready screenplay format.

Given a scene from a novel, convert it to a visual screenplay suitable for comic panels.

RULES:
- Convert ALL prose descriptions to OBSERVABLE ACTIONS. 
  "She felt afraid" → "She backs against the wall, eyes wide, hands trembling"
- Compress dialogue to ≤35 words per speech bubble. Split long speeches across multiple bubbles.
- Remove all interiority (thoughts, feelings, backstory) unless it can be shown visually.
  Interior monologue → thought bubbles (use sparingly, max 1-2 per scene)
- Add SFX annotations where appropriate: [SFX: CRASH], [SFX: footsteps]
- Preserve the emotional arc of the scene.
- Mark scene transitions: [TRANSITION: smash cut], [TRANSITION: fade]

Output JSON:
{
  "scene_id": "...",
  "location_id": "...",
  "characters": ["char_001", "char_002"],
  "beats": [
    {
      "type": "action" | "dialogue" | "sfx" | "transition",
      "character_id": "..." (if applicable),
      "content": "description of action or dialogue text",
      "direction": "optional visual direction notes"
    }
  ]
}
```

**Parallelism**: Process scenes in batches of 5 to respect rate limits. Use `asyncio.gather` with semaphore.

---

### Stage 4: Panel Breakdown

**Model**: Gemini 2.5 Flash
**Input**: `screenplays/{scene_id}.json`, `story_bible.json`
**Output**: `panels/{scene_id}/panel_NNN.json`
**Cost**: ~$0.27 for entire novel
**Checkpoint**: No

**System prompt** (for `prompts/panel_breakdown.txt`):
```
You are a comic book artist planning panel layouts from a screenplay.

Given a scene screenplay, break it into 3-8 individual comic panels.

For each panel, specify:
- panel_number (1-indexed)
- shot_type: "extreme-close-up", "close-up", "medium-close", "medium", "medium-wide", "wide", "extreme-wide"
- camera_angle: "eye-level", "low-angle", "high-angle", "dutch-angle", "bird-eye", "worm-eye"
- characters_present: [character IDs visible in this panel]
- character_actions: {char_id: "what they're physically doing"}
- character_expressions: {char_id: "facial expression"}
- character_positions: {char_id: "left foreground", "center", "right background", etc.}
- background_description: what's visible behind characters
- lighting: specific lighting description
- mood: single word
- dialogue: [{character_id, text, type: "speech"|"thought"|"narration"}]
- sfx: optional sound effect text
- transition_note: optional, for assembly hints

PACING RULES:
- Action scenes: more panels (6-8), faster cuts, closer shots
- Dialogue scenes: fewer panels (3-5), medium shots, shot-reverse-shot pattern
- Emotional beats: use a single wide panel or extreme close-up for emphasis
- Scene openers: start with an establishing wide shot of the location
- Never put more than 3 speech bubbles in one panel
- Vary shot types — never use the same shot_type twice in a row

Output a JSON array of panel objects.
```

---

### Stage 5: Image Prompt Generation

**Model**: Gemini 2.5 Flash
**Input**: `panels/{scene_id}/panel_NNN.json`, `story_bible.json`
**Output**: `prompts/{scene_id}/panel_NNN.json`
**Cost**: ~$0.41 for entire novel
**Checkpoint**: No

**This stage assembles the final image prompt from 4 components**:

```
[STYLE TEMPLATE]           ← from config.yaml, fixed for entire project
[LOCATION ANCHOR]          ← from story_bible.locations[].visual_anchor
[CHARACTER ANCHOR(S)]      ← from story_bible.characters[].visual_anchor, VERBATIM
[SCENE DIRECTION]          ← from panel JSON (shot, angle, action, mood, lighting)
"No text. No speech bubbles. No captions. No lettering. Single panel only."
```

**The LLM's job is NOT to write a creative prompt.** It is to assemble the components into a well-structured natural language paragraph, resolving any conflicts (e.g., character position + camera angle). The character anchors must appear word-for-word — the LLM may rearrange sentence order but must not change the anchor text.

**System prompt** (for `prompts/image_prompt.txt`):
```
You assemble image generation prompts for comic panels.

You receive:
1. A style template (use verbatim as the opening)
2. A location visual anchor (use verbatim or near-verbatim)
3. Character visual anchors (use VERBATIM — do not change a single word)
4. Panel direction (shot type, camera angle, character actions, expressions, positions, lighting, mood)

Combine these into a single natural-language prompt paragraph. The character visual anchors
MUST appear word-for-word. You may arrange the order and add connecting words,
but the anchor text itself is immutable.

ALWAYS end the prompt with:
"No text. No speech bubbles. No captions. No lettering. Single panel only."

Also output the list of character reference image paths that should be sent 
as multi-reference inputs to the image model (4 images per character present).

Output JSON matching the ImagePrompt schema.
```

---

### Stage 6: Image Generation

**Model**: FLUX.2 Pro via Together AI
**Input**: `prompts/{scene_id}/panel_NNN.json`, reference images from `refs/`
**Output**: `images/{scene_id}/panel_NNN.png`
**Cost**: ~$18–24 for 600 panels at $0.03/image
**Checkpoint**: Yes — user reviews generated panels per chapter

**For each panel**:
1. Read the prompt JSON.
2. Load the character reference images listed in `reference_image_paths`.
3. Call FLUX.2 Pro with the prompt and up to 8 reference images.
4. Save the result to `images/{scene_id}/panel_NNN.png`.
5. (Optional) Run Real-ESRGAN 4x upscale and save as `panel_NNN_upscaled.png`.

**Together AI multi-reference call**:
```python
import base64
from together import Together

client = Together(api_key=config.together_api_key)

# Load reference images as base64
ref_images = []
for path in prompt.reference_image_paths:
    with open(path, "rb") as f:
        ref_images.append(base64.b64encode(f.read()).decode())

# For multi-reference, pass the first reference as image_url
# and additional references in the prompt or via the API's multi-ref feature
response = client.images.generate(
    model="black-forest-labs/FLUX.2-pro",
    prompt=prompt.full_prompt,
    width=prompt.width,
    height=prompt.height,
    steps=prompt.steps,
    n=1,
    response_format="b64_json",
    image_url=f"data:image/png;base64,{ref_images[0]}" if ref_images else None,
)

# Decode and save
image_data = base64.b64decode(response.data[0].b64_json)
with open(output_path, "wb") as f:
    f.write(image_data)
```

**IMPORTANT**: The Together AI multi-reference API for FLUX.2 Pro supports up to 8 reference images. Check the current API docs for the exact parameter name — it may be `image_url` (single) or `image_urls` (multiple). If the API only supports single image_url, you will need to use the BFL direct API instead, which supports the `references` parameter for multiple images.

**Rate limiting**: Together AI has rate limits. Implement exponential backoff with jitter. Use a semaphore to limit concurrent requests (start with 3-5 concurrent).

**Retry logic**: If a panel generation fails, log the failure to `state.json` items_failed list. The `--retry-failed` CLI flag will re-run only failed panels.

---

### Stage 7: Comic Assembly

**Libraries**: Pillow (image compositing), ReportLab or Pillow (PDF export)
**Input**: `images/`, `panels/` (for dialogue data)
**Output**: `pages/`, `exports/`
**Cost**: $0 (pure computation)
**Checkpoint**: No

**Page layout algorithm**:
1. Group panels into pages. Rules:
   - 2-4 panels per page (standard comic pacing)
   - Wide/establishing shots can be full-width
   - Action sequences: more panels, smaller
   - Emotional beats: fewer panels, larger
   - Never split a scene's panels across pages if possible
2. Arrange panels in a grid with 20px gutters between panels and 40px page margins.
3. Common layouts (for a 2480x3508 page at 300 DPI):
   - 2 panels: two rows, full width each
   - 3 panels: one full-width top + two half-width bottom (or vice versa)
   - 4 panels: 2x2 grid
4. Composite speech bubbles:
   - Draw rounded rectangle with white fill and black 2px border
   - Position above the speaking character's head
   - Use a triangle "tail" pointing to the character
   - Render text with Pillow's `ImageDraw.text()` using a comic font (CC Wild Words, Blambot, or similar)
   - Thought bubbles: use a cloud shape instead of rounded rect
   - Narration boxes: rectangular boxes with colored background, positioned at top or bottom of panel
5. Add page numbers.

**Export formats**:
- **PDF**: Use Pillow to save each page as a high-res PNG, then combine with `img2pdf` or ReportLab.
- **CBZ**: ZIP all page PNGs into a .cbz file (literally a renamed .zip).
- **EPUB**: Use `ebooklib` to create an EPUB with each page as an image.

---

## 6. CLI Interface

Use `click` for the CLI.

```
Usage: pipeline [OPTIONS] COMMAND [ARGS]

Commands:
  init          Create a new project from a novel file
  run           Run one or all pipeline stages
  status        Show pipeline progress and costs
  review        Start local review server
  approve       Mark a checkpoint stage as approved
  export        Run assembly and export

Examples:
  pipeline init --input novel.epub --name my-project
  pipeline run extract --project ./my-project
  pipeline run all --project ./my-project
  pipeline run generate --project ./my-project --scene scene_012
  pipeline run generate --project ./my-project --retry-failed
  pipeline status --project ./my-project
  pipeline approve --project ./my-project --stage index
  pipeline export --project ./my-project --format pdf,cbz
```

**`run all` behavior**: Runs stages sequentially. When it hits a checkpoint stage (1, 2, 6), it pauses and prints a message telling the user to review the output and run `pipeline approve`. This is not a blocking wait — the command exits, and the user runs it again after review.

**Resumability**: Every stage checks `state.json` before starting. If a stage is `complete`, it skips. If it's `running` with partial progress, it resumes from where it left off (using `items_done` count). If `failed`, it shows the error and suggests `--retry-failed`.

---

## 7. Dependencies

```toml
[project]
name = "novel-to-comic"
version = "0.1.0"
requires-python = ">=3.12"

[project.dependencies]
click = ">=8.0"
pydantic = ">=2.0"
pyyaml = ">=6.0"
httpx = ">=0.27"             # Async HTTP client
together = ">=1.0"           # Together AI SDK (FLUX.2 Pro)
anthropic = ">=0.40"         # Claude API
google-genai = ">=1.0"       # Gemini API  
openai = ">=1.50"            # For embeddings only
qdrant-client = ">=1.12"     # Vector store
ebooklib = ">=0.18"          # EPUB parsing
Pillow = ">=10.0"            # Image compositing
img2pdf = ">=0.5"            # PDF export
rich = ">=13.0"              # Pretty CLI output
tenacity = ">=9.0"           # Retry logic

[project.optional-dependencies]
dev = ["pytest", "ruff"]
```

**External services**:
- Qdrant: Run via Docker (`docker run -d -p 6333:6333 qdrant/qdrant:latest`)
- No other local services required — all AI models are called via API

---

## 8. Implementation Order

Build in this exact order. Each step should be tested before moving on.

### Step 1: Skeleton + Config + State Machine
- [ ] Set up project structure with `pyproject.toml`
- [ ] Implement `config.py` (Pydantic settings, load from YAML)
- [ ] Implement `state.py` (read/write `state.json`, stage status transitions)
- [ ] Implement `cli.py` with `init`, `run`, `status`, `approve` commands (stubs)
- [ ] Test: `pipeline init --input test.txt` creates project directory and state.json

### Step 2: Stage 1 — Extraction
- [ ] Implement novel text extraction (EPUB via ebooklib, TXT direct read)
- [ ] Implement `clients/gemini.py` (async wrapper with retry)
- [ ] Write `prompts/extraction.txt` system prompt
- [ ] Implement `s1_extract.py` — full novel → Story Bible JSON
- [ ] Implement `models/story_bible.py` Pydantic models
- [ ] Test: Run on a public domain short story (e.g., "The Gift of the Magi" by O. Henry). Validate the Story Bible makes sense.

### Step 3: Stage 2 — RAG Index
- [ ] Implement `rag/chunker.py` (scene-boundary chunking)
- [ ] Implement `clients/embeddings.py` (OpenAI embeddings wrapper)
- [ ] Implement `rag/store.py` (Qdrant operations: create collection, upsert, search)
- [ ] Test: Index the test story, query for a character name, verify relevant chunks returned.

### Step 4: Stage 2 — Character Refs + Location Plates
- [ ] Implement `clients/flux.py` (Together AI image generation wrapper)
- [ ] Implement character reference generation in `s2_index.py`
- [ ] Implement location plate generation
- [ ] Test: Generate refs for 2 characters from the test story. Visually inspect.

### Step 5: Stages 3–5 — LLM Pipeline
- [ ] Implement `clients/claude.py` (async wrapper with retry)
- [ ] Write system prompts for stages 3, 4, 5
- [ ] Implement `s3_screenplay.py`, `s4_panels.py`, `s5_prompts.py`
- [ ] Implement `models/panel.py` and `models/prompt.py`
- [ ] Test: Run stages 3-5 on the test story. Inspect the final prompts — they should contain verbatim character anchors.

### Step 6: Stage 6 — Image Generation
- [ ] Implement `s6_generate.py` with multi-reference support
- [ ] Add rate limiting, retry logic, semaphore for concurrent requests
- [ ] Add failed panel tracking to state.json
- [ ] Test: Generate 10-15 panels from the test story. Check character consistency across panels.

### Step 7: Stage 7 — Assembly
- [ ] Implement page layout algorithm
- [ ] Implement speech bubble compositing
- [ ] Implement PDF/CBZ export
- [ ] Test: Assemble the test story panels into a multi-page comic. Open the PDF.

### Step 8: CLI Polish + Review Server
- [ ] Wire all stages into `cli.py` `run all` command with checkpoint pausing
- [ ] Implement `--retry-failed` and `--scene` flags
- [ ] Implement `status` command with rich table output
- [ ] (Optional) Build a simple Flask/FastAPI review server that shows thumbnails

---

## 9. Testing Strategy

### PoC Test Material
Use public domain short stories for testing. Good candidates:
- "The Gift of the Magi" by O. Henry (~2,200 words, 2 characters, 2 locations, emotional arc)
- "The Tell-Tale Heart" by Edgar Allan Poe (~2,100 words, 1 character, 1 location, psychological tension)
- "The Lottery" by Shirley Jackson (~3,400 words, multiple characters, 1 location, building dread)

For a slightly larger test:
- "A Christmas Carol" by Charles Dickens (~28,500 words, multiple characters, multiple locations, 5 acts)

### What to Validate at Each Stage
1. **Extraction**: Visual anchors are physical descriptions only (no personality). Scene count is 3-8 for short stories, 30-60 for novels.
2. **RAG**: Querying a character name returns chunks where they appear. Querying a location returns relevant scene chunks.
3. **Screenplay**: No interiority remains. All dialogue ≤35 words. Actions are observable.
4. **Panels**: Shot types vary. 3-8 panels per scene. Establishing shots open scenes.
5. **Prompts**: Character anchors appear VERBATIM. Style template is present. Ends with "No text" instruction.
6. **Images**: Characters are recognizable across panels (this is the hard test). Same outfit, same hair, same face.
7. **Assembly**: Panels are arranged correctly. Speech bubbles are readable. PDF opens in a reader.

---

## 10. API Reference Quick Sheet

### Together AI (FLUX.2 Pro)
```python
from together import Together
client = Together(api_key="...")
response = client.images.generate(
    model="black-forest-labs/FLUX.2-pro",
    prompt="...",
    width=1024, height=1344, steps=28, n=1,
    response_format="b64_json",
)
# response.data[0].b64_json contains base64-encoded PNG
```
Pricing: $0.030/image at 1MP. Rate limits apply.

### Anthropic (Claude Sonnet 4.6)
```python
import anthropic
client = anthropic.Anthropic(api_key="...")
message = client.messages.create(
    model="claude-sonnet-4-6-20250514",
    max_tokens=8192,
    system="...",
    messages=[{"role": "user", "content": "..."}],
)
# message.content[0].text contains the response
```
Pricing: $3/M input tokens, $15/M output tokens.

### Google Gemini 2.5 Pro / Flash
```python
from google import genai
client = genai.Client(api_key="...")
response = client.models.generate_content(
    model="gemini-2.5-pro",  # or "gemini-2.5-flash"
    contents="...",
    config=genai.types.GenerateContentConfig(
        system_instruction="...",
        response_mime_type="application/json",
    ),
)
# response.text contains the JSON response
```
Pricing: Gemini 2.5 Pro ~$1.25/M input, $10/M output. Flash ~$0.15/M input, $0.60/M output.

### OpenAI Embeddings
```python
from openai import OpenAI
client = OpenAI(api_key="...")
response = client.embeddings.create(
    model="text-embedding-3-small",
    input=["text to embed"],
)
# response.data[0].embedding contains the 1536-dim vector
```
Pricing: $0.02/M tokens.

### Qdrant
```python
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, Distance, VectorParams

client = QdrantClient(host="localhost", port=6333)

# Create collection
client.create_collection("scenes", vectors_config=VectorParams(size=1536, distance=Distance.COSINE))

# Upsert
client.upsert("scenes", points=[
    PointStruct(id=1, vector=[...], payload={"scene_id": "scene_001", "text": "..."})
])

# Search
results = client.query_points("scenes", query=[...], limit=5,
    query_filter=Filter(must=[FieldCondition(key="scene_id", match=MatchValue(value="scene_001"))]))
```

---

## 11. Known Risks and Mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Character drift across panels | High | Multi-reference images + verbatim anchors. Review at chapter boundaries. Regenerate from refs, never from previous panels. |
| FLUX.2 API rate limits | Medium | Exponential backoff + semaphore (3-5 concurrent). Batch generation by chapter. |
| LLM outputs invalid JSON | Medium | Use `response_mime_type="application/json"` for Gemini. For Claude, wrap in JSON extraction + Pydantic validation + retry. |
| Story Bible extraction misses characters | Low | Human review checkpoint. User can manually edit `story_bible.json` before proceeding. |
| Multi-character scenes look wrong | High | Generate characters separately + composite (fallback). Or: use FLUX.2 multi-ref with separate anchor packs per character. |
| Image generation costs spike | Medium | Track costs in state.json. Add a `--cost-limit` flag that pauses if exceeded. Use FLUX.2 klein for drafts. |
| Novel too long for context window | Low | Gemini 2.5 Pro handles 1M tokens (~750K words). If novel exceeds this, split into volumes. |

---

## 12. Future Phases (Out of Scope for PoC)

**Phase 2: Animation** — Add image-to-video via Hailuo 02 API ($0.27/clip), TTS via ElevenLabs ($22/mo), lip-sync via Sync.so ($0.05-0.13/sec), assembly via FFmpeg.

**Phase 3: Web Review UI** — Flask/FastAPI server showing pipeline progress, Story Bible editor, panel thumbnail gallery with approve/reject/regenerate buttons, side-by-side novel text + comic panels.

**Phase 4: Quality Improvements** — LoRA training per character for self-hosted consistency, ControlNet OpenPose for pose control, ADetailer for face correction, Real-ESRGAN upscaling, background compositing from location plates.

---

## 13. Summary: What to Build First

The PoC goal is: **take a 10-page short story and produce a 10-15 page comic PDF**.

1. Start with "The Gift of the Magi" as test input.
2. Build the skeleton (config, state, CLI).
3. Build stage 1 (extraction) and validate the Story Bible.
4. Build stage 2 (RAG + refs) and validate character images.
5. Build stages 3-5 (LLM pipeline) and validate the prompts contain verbatim anchors.
6. Build stage 6 (image gen) and check consistency across panels.
7. Build stage 7 (assembly) and export a PDF.
8. Open the PDF. You have a comic.
# Stage I/O Contracts

Quick reference for what each stage reads and writes. Each stage runs independently — it reads its inputs from disk and writes its outputs to disk. Never add cross-stage logic.

_This file is manually maintained. Update it when stage I/O changes._

---

## Stages at a glance

| # | Stage | CLI name | LLM | Checkpoint? |
|---|-------|----------|-----|-------------|
| 1 | Extract | `extract` | Gemini 3.1 Pro | ✅ Yes |
| 2 | Index | `index` | FLUX/Gemini (image gen) | ✅ Yes |
| 3 | Screenplay | `screenplay` | Gemini 3.1 Pro | ❌ No |
| 4 | Panels | `panels` | Gemini 3.1 Flash-Lite | ❌ No |
| 5 | Prompts | `prompts` | Gemini 3.1 Flash-Lite | ❌ No |
| 6 | Generate | `generate` | FLUX/Gemini (image gen) | ✅ Yes |
| 7 | Assemble | `assemble` | None (deterministic) | ❌ No |

Checkpoint stages pause at `awaiting_review` state. Advance with `pipeline approve <stage>` or the TUI/web approval screen.

---

## Stage 1 — Extract (`s1_extract.py`)

**Reads:**
- `input/novel.txt` or `input/novel.epub`

**Writes:**
- `story_bible.json` ← central artifact; all downstream stages read this
- `scenes/scene_NNN.txt` (one file per scene)

**What it does:** Uses 1M-context Gemini Pro to extract characters, locations, scenes, narrative arcs, and props from the entire novel. Also splits the novel into per-scene text files for downstream stages.

---

## Stage 2 — Index (`s2_index.py`)

**Reads:**
- `story_bible.json`
- `scenes/scene_NNN.txt`

**Writes:**
- `refs/char_NNN/` — Character reference sheets: `front.png`, `three_quarter.png`, `side.png`, `action.png`
- `plates/loc_NNN.png` — Location background plates
- optional Qdrant collection when `enable_rag_index: true`

**What it does:** Generates character reference images (4 angles) and location plates using the image generation router. These reference images are injected into Stage 6 prompts. The experimental RAG index is skipped by default because downstream stages currently read scene files directly.

---

## Stage 3 — Screenplay (`s3_screenplay.py`)

**Reads:**
- `story_bible.json`
- `scenes/scene_NNN.txt` (per scene)

**Writes:**
- `screenplays/scene_NNN.json` (one `Screenplay` JSON per scene)

**What it does:** Converts raw scene prose into screenplay format with beats (action/dialogue/SFX/transition). Injects scene-specific Story Bible context directly into the prompt.

---

## Stage 4 — Panels (`s4_panels.py`)

**Reads:**
- `screenplays/scene_NNN.json`
- `story_bible.json`

**Writes:**
- `panels/scene_NNN/panel_NNN.json` (one `PanelBreakdown` JSON per panel)

**What it does:** Converts each screenplay beat sequence into panel-by-panel breakdowns. Specifies shot type, camera angle, character positions, expressions, dialogue, and SFX per panel.

---

## Stage 5 — Prompts (`s5_prompts.py`)

**Reads:**
- `panels/scene_NNN/panel_NNN.json`
- `story_bible.json` (for character/location visual anchors)
- `refs/char_NNN/*.png` (reference image paths for multi-reference injection)
- `plates/loc_NNN.png` (plate paths)

**Writes:**
- `prompts/scene_NNN/panel_NNN.json` (one `ImagePrompt` JSON per panel)

**What it does:** Assembles the complete image generation prompt for each panel. Injects `visual_anchor` fields verbatim, style template, and reference image paths. The `full_prompt` string is what goes directly to the image model.

---

## Stage 6 — Generate (`s6_generate.py`)

**Reads:**
- `prompts/scene_NNN/panel_NNN.json`
- `refs/char_NNN/*.png` (loaded as binary for multi-reference)
- `plates/loc_NNN.png` (loaded as binary)

**Writes:**
- `images/scene_NNN/panel_NNN.png`

**What it does:** Runs image generation. Routes to Gemini via Vertex AI or Together AI (FLUX) based on model name. Runs async with rate limiting. Pauses for human review of generated panels before Stage 7.

---

## Stage 7 — Assemble (`s7_assemble.py`)

**Reads:**
- `images/scene_NNN/panel_NNN.png`
- `panels/scene_NNN/panel_NNN.json` (for dialogue, SFX, layout hints)
- `story_bible.json` (character names for bubble attribution)

**Writes:**
- `assembly/pages/page_NNN.json` ← **canonical editing surface** (ComicPage model)
- `assembly/html/page_NNN.html` (HTML preview — open in browser, edit theme.css, hard-refresh)
- `assembly/pages/page_NNN.png` (Playwright screenshot)
- `assembly/theme.css` (written on first run; user can edit freely)
- `exports/comic.pdf` and/or `exports/comic.cbz` (on export)

**What it does:** Groups panels into pages (up to `max_panels_per_page`), builds ComicPage JSON, renders HTML with the theme system, and screenshots to PNG via Playwright. The `page_NNN.json` file is the editing surface for the future web drag-and-drop editor.

---

## Re-running a single stage

```bash
# Re-run panels for one scene
pipeline run panels --scene scene_012

# Re-run generate for one panel
pipeline regen --scene scene_012 --panel 3

# Re-export without regenerating images
pipeline export --format pdf
```

State machine respects partial completion — already-done items are skipped unless `--force` is passed.

# Canary — Agent Guidelines

Compact instruction file for every coding-agent session. Detailed reference:
`docs/reference/agent-context.md`.

## Work Style

- State assumptions before implementing when the request is ambiguous.
- Prefer the minimum code that solves the request.
- Touch only files required by the task. Do not refactor adjacent code unless
  the request requires it.
- Match existing style, even when you would personally choose another pattern.
- Mention unrelated issues you notice; do not fix them unless asked.
- Remove only unused imports/variables/functions introduced by your own change.
- For multi-step work, define success criteria and verify them.

## Project Snapshot

Canary is a Python/React app that turns novels into comic books via an 8-stage
pipeline. Each stage is discrete, resumable, and produces inspectable JSON/file
output. The pipeline is orchestrated through a FastAPI web server — there is no
`pipeline run` CLI command. Use the web UI or call the API directly.

**8 pipeline stages (in order):**

| # | Stage name | What it does |
|---|-----------|--------------|
| 1 | `extract` | Novel → Story Bible JSON |
| 2 | `cast` | Story Bible → character refs + location plates |
| 3 | `adapt` | Scene prose → screenplay format |
| 4 | `plan` | Screenplay → page/panel layout plan |
| 5 | `storyboard` | Layout plan → panel breakdown JSON |
| 6 | `direct` | Planned panels → image prompts |
| 7 | `draw` | Image prompts → panel PNGs |
| 8 | `compose` | Panel images + bubble/SFX JSON → PDF/CBZ export |

**Current focus:** `draw` (stage 7) generation and `compose` (stage 8) assembly.

## Must-Know Rules

- **No `pipeline run` CLI.** Pipeline operations (run, approve, status, export)
  are HTTP API endpoints on the web server. The CLI only has `init` and `serve`.
  See `server/routers/pipeline.py` for all pipeline endpoints.
- Do not collapse stages or add cross-stage logic. Each stage reads its inputs
  from disk and writes its own outputs.
- Preserve `visual_anchor` text verbatim. Never paraphrase anchors in prompts.
- Text belongs in Stage 8 (`compose`) post-processing, never inside generated
  panel images.
- `compose/pages/page_NNN.json` is the canonical Stage 8 editing surface.
- Every stage `run()` accepts `on_event`; add `emit()` calls beside new
  `console.print()` calls.
- Do not build the visual drag-and-drop editor before pinned bubble SVG tails
  exist (`tail_x`/`tail_y` target points are the planned model change).
- Keep model names/configuration in `config.py` or project `config.yaml`, not in
  prompt templates.
- Breaking JSON/model changes are acceptable for now; do not add legacy shims
  unless explicitly requested.
- **Style gate:** The backend blocks `POST /run` for any post-extract stage if no
  style is selected (`is_style_selected` in `styles.py`). The status API returns
  `style_selected: bool` sourced from `config.yaml`. Frontend uses this field
  (not `useStyles` data) for gate checks to avoid stale-cache bugs.

## Where To Look

- Detailed agent reference: `docs/reference/agent-context.md`
- Web server + all pipeline API endpoints: `server/routers/pipeline.py`
- CLI (`init` + `serve` only): `novel_to_comic/src/novel_to_comic/cli.py`
- Config loading/defaults: `novel_to_comic/src/novel_to_comic/config.py`
- Pipeline state machine: `novel_to_comic/src/novel_to_comic/state.py`
- Stage definitions (all 8): `novel_to_comic/src/novel_to_comic/stages/`
- Event schema/SSE: `novel_to_comic/src/novel_to_comic/events.py`
- Image routing: `novel_to_comic/src/novel_to_comic/clients/flux.py`
- Layout planning models + helpers: `novel_to_comic/src/novel_to_comic/layout_planning.py`
- Assembly renderer: `novel_to_comic/src/novel_to_comic/assembly/html_renderer.py`
- Comic editing models: `novel_to_comic/src/novel_to_comic/models/comic_page.py`

## Context Hygiene

- Prefer targeted `rg` searches over broad repository scans.
- Avoid reading generated artifacts, binary assets, lockfiles, and logs unless
  they are directly relevant.
- For broad searches, exclude noisy paths such as `.git`, `node_modules`,
  `web/dist`, `.playwright-cli`, project outputs, and binary assets.
- Start a fresh session for unrelated work instead of carrying long histories.

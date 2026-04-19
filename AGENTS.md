Behavioral guidelines for coding agents in this repo. Keep this file short:
it is loaded into every session. Open `docs/reference/agent-context.md` only
when you need detailed pipeline, model, stage, assembly, or artifact context.

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

Canary is an early-MVP Python/React app that turns novels into comic books via a
7-stage resumable pipeline:

1. extract story bible
2. build index and visual references
3. write screenplay
4. break screenplay into panels
5. assemble image prompts
6. generate panel images
7. assemble/export comic pages

Current focus: Stage 6 generation and Stage 7 assembly.

## Must-Know Rules

- Do not collapse stages or add cross-stage logic. Each stage reads its inputs
  from disk and writes its own outputs.
- Preserve `visual_anchor` text verbatim. Never paraphrase anchors in prompts.
- Text belongs in Stage 7 post-processing, never inside generated panel images.
- `assembly/pages/page_NNN.json` is the canonical Stage 7 editing surface.
- Every stage `run()` accepts `on_event`; add `emit()` calls beside new
  `console.print()` calls.
- Do not build the visual drag-and-drop editor before pinned bubble SVG tails
  exist (`tail_x/tail_y` target points are the planned model change).
- Keep model names/configuration in `config.py` or project `config.yaml`, not in
  prompt templates.
- Breaking JSON/model changes are acceptable for now; do not add legacy shims
  unless explicitly requested.

## Where To Look

- Detailed agent reference: `docs/reference/agent-context.md`
- CLI and stage routing: `novel_to_comic/src/novel_to_comic/cli.py`
- Config loading/defaults: `novel_to_comic/src/novel_to_comic/config.py`
- Pipeline state machine: `novel_to_comic/src/novel_to_comic/state.py`
- Event schema/SSE notes: `novel_to_comic/src/novel_to_comic/events.py`
- Image routing: `novel_to_comic/src/novel_to_comic/clients/flux.py`
- Assembly renderer: `novel_to_comic/src/novel_to_comic/assembly/html_renderer.py`
- Comic editing models: `novel_to_comic/src/novel_to_comic/models/comic_page.py`

## Context Hygiene

- Prefer targeted `rg` searches over broad repository scans.
- Avoid reading generated artifacts, binary assets, lockfiles, and logs unless
  they are directly relevant.
- For broad searches, exclude noisy paths such as `.git`, `node_modules`,
  `web/dist`, `.playwright-cli`, project outputs, and binary assets.
- Start a fresh session for unrelated work instead of carrying long histories.

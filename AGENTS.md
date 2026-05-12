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

Canary is a Python/React app that turns novels into comic books via a 9-stage
pipeline. Each stage is discrete, resumable, and produces inspectable JSON/file
output. The pipeline is orchestrated through a FastAPI web server — there is no
`pipeline run` CLI command. Use the web UI or call the API directly.

**Pipeline stages (in order):**

| # | Stage name | What it does |
|---|-----------|--------------|
| 1 | `extract` | Novel → Story Bible JSON |
| 2 | `style` | Story Bible → visual style options + sample images |
| 3 | `cast` | Story Bible + active style → character refs + location plates |
| 4 | `adapt` | Scene prose → screenplay format |
| 5 | `plan` | Screenplay → page/panel layout plan |
| 6 | `storyboard` | Layout plan → panel breakdown JSON |
| 7 | `direct` | Planned panels → image prompts |
| 8 | `draw` | Image prompts → panel PNGs |
| 9 | `compose` | Panel images + bubble/SFX JSON → PDF/CBZ export |

**Note on file numbering:** Stage file prefixes are implementation history, not
the contract. Use `STAGE_NAMES` in `state.py` and `REGISTRY` in `stages/__init__.py`
as the source of truth. Two stages currently share the `s5` prefix, and `direct`
is implemented in `s6_storyboard.py`.

**Current focus:** style selection/gating, draw-stage image review and targeted
regeneration, compose editor/export, and credits/billing accuracy.

## Must-Know Rules

- **No `pipeline run` CLI.** Pipeline operations (run, approve, status, export)
  are HTTP API endpoints on the web server. The CLI only has `init` and `serve`.
  See `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py` for all pipeline endpoints.
- Do not collapse stages or add cross-stage logic. Each stage reads its inputs
  from disk and writes its own outputs.
- Preserve `visual_anchor` text verbatim. Never paraphrase anchors in prompts.
- Text belongs in Stage 9 (`compose`) post-processing, never inside generated
  panel images.
- `compose/pages/page_NNN.json` is the canonical Stage 9 editing surface.
- Every stage `run()` accepts `on_event`; add `emit()` calls beside new
  `console.print()` calls.
- The compose visual editor and pinned SVG bubble tails exist. Preserve the
  `tail_x`/`tail_y` panel-relative target-point contract when editing lettering
  or renderer code.
- Keep model names/configuration in `config.py` or project `config.yaml`, not in
  prompt templates.
- Breaking JSON/model changes are acceptable for now; do not add legacy shims
  unless explicitly requested.
- **Style gate:** The backend blocks `POST /run` for any post-style stage if no
  style is selected (`is_style_selected` in `styles.py`). The status API returns
  `style_selected: bool` sourced from `config.yaml`. Frontend uses this field
  (not `useStyles` data) for gate checks to avoid stale-cache bugs.

## Where To Look

All paths are repo-relative.

- Detailed agent reference: `docs/reference/agent-context.md`
- Web server + all pipeline API endpoints: `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py`
- CLI (`init` + `serve` only): `novel_to_comic/src/novel_to_comic/cli.py`
- Config loading/defaults: `novel_to_comic/src/novel_to_comic/config.py`
- Pipeline state machine: `novel_to_comic/src/novel_to_comic/state.py`
- Stage definitions (all 8): `novel_to_comic/src/novel_to_comic/stages/`
- Event schema/SSE: `novel_to_comic/src/novel_to_comic/events.py`
- Image routing: `novel_to_comic/src/novel_to_comic/clients/flux.py`
- Layout planning models + helpers: `novel_to_comic/src/novel_to_comic/layout_planning.py`
- Assembly renderer: `novel_to_comic/src/novel_to_comic/assembly/html_renderer.py`
- Comic editing models: `novel_to_comic/src/novel_to_comic/models/comic_page.py`
- Auth (Supabase JWT, `get_current_user`): `novel_to_comic/src/novel_to_comic/server/auth.py`
- Credit reservation/debit: `novel_to_comic/src/novel_to_comic/server/credits.py`
- Supabase client singleton: `novel_to_comic/src/novel_to_comic/server/db.py`
- Stripe billing + webhooks: `novel_to_comic/src/novel_to_comic/server/routers/billing.py`

## Context Hygiene

- Prefer targeted `rg` searches over broad repository scans.
- Avoid reading generated artifacts, binary assets, lockfiles, and logs unless
  they are directly relevant.
- For broad searches, exclude noisy paths such as `.git`, `node_modules`,
  `web/dist`, `.playwright-cli`, project outputs, and binary assets.
- Start a fresh session for unrelated work instead of carrying long histories.

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
- Every stage `run()` receives a `StageRuntime` as `ctx`. Use `ctx.log()`,
  `ctx.progress()`, `ctx.record_item_done()`, etc. — do not thread `on_event`
  manually. Pass `ctx.on_event` to `make_progress()` for Rich progress bars.
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
- Stage definitions (all 9): `novel_to_comic/src/novel_to_comic/stages/`
- Stage lifecycle (events, state transitions, cost): `novel_to_comic/src/novel_to_comic/stage_runtime.py`
- Artifact paths + typed read/write: `novel_to_comic/src/novel_to_comic/artifacts.py`
- Event schema/SSE: `novel_to_comic/src/novel_to_comic/events.py`
- Image generation: `novel_to_comic/src/novel_to_comic/clients/flux.py` + `novel_to_comic/src/novel_to_comic/ai/finalisation.py`
- Prompt build + re-render: `novel_to_comic/src/novel_to_comic/prompt_assembly.py`
- Panel record CRUD (s5→s9): `novel_to_comic/src/novel_to_comic/panel_store.py`
- Layout planning models + helpers: `novel_to_comic/src/novel_to_comic/layout_planning.py`
- Narration decision editing: `novel_to_comic/src/novel_to_comic/server/narration_editor.py`
- Assembly renderer: `novel_to_comic/src/novel_to_comic/assembly/html_renderer.py`
- Comic editing models: `novel_to_comic/src/novel_to_comic/models/comic_page.py`
- Panel acceptance state: `novel_to_comic/src/novel_to_comic/server/panel_acceptance.py`
- Shared FastAPI deps (project resolution): `novel_to_comic/src/novel_to_comic/server/deps.py`
- Credit-guaranteed generation jobs: `novel_to_comic/src/novel_to_comic/server/credited_job.py`
- Credit reservation/debit: `novel_to_comic/src/novel_to_comic/server/credits.py`
- Auth (Supabase JWT, `get_current_user`): `novel_to_comic/src/novel_to_comic/server/auth.py`
- Supabase client singleton: `novel_to_comic/src/novel_to_comic/server/db.py`
- Stripe billing + webhooks: `novel_to_comic/src/novel_to_comic/server/routers/billing.py`
- Labs experimentation: `novel_to_comic/src/novel_to_comic/labs/` + `novel_to_comic/src/novel_to_comic/server/routers/labs.py`
- R2 export upload: `novel_to_comic/src/novel_to_comic/storage.py`

## Context Hygiene

- Prefer targeted `rg` searches over broad repository scans.
- Avoid reading generated artifacts, binary assets, lockfiles, and logs unless
  they are directly relevant.
- For broad searches, exclude noisy paths such as `.git`, `node_modules`,
  `web/dist`, `.playwright-cli`, project outputs, and binary assets.
- Start a fresh session for unrelated work instead of carrying long histories.

<!-- CODEGRAPH_START -->
## CodeGraph

This project has a CodeGraph MCP server (`codegraph_*` tools) configured. CodeGraph is a tree-sitter-parsed knowledge graph of every symbol, edge, and file. Reads are sub-millisecond and return structural information grep cannot.

### When to prefer codegraph over native search

Use codegraph for **structural** questions — what calls what, what would break, where is X defined, what is X's signature. Use native grep/read only for **literal text** queries (string contents, comments, log messages) or after you already have a specific file open.

| Question | Tool |
|---|---|
| "Where is X defined?" / "Find symbol named X" | `codegraph_search` |
| "What calls function Y?" | `codegraph_callers` |
| "What does Y call?" | `codegraph_callees` |
| "How does X reach/become Y? / trace the flow from X to Y" | `codegraph_trace` (one call = the whole path, incl. callback/React/JSX dynamic hops) |
| "What would break if I changed Z?" | `codegraph_impact` |
| "Show me Y's signature / source / docstring" | `codegraph_node` |
| "Give me focused context for a task/area" | `codegraph_context` |
| "See several related symbols' source at once" | `codegraph_explore` |
| "What files exist under path/" | `codegraph_files` |
| "Is the index healthy?" | `codegraph_status` |

### Rules of thumb

- **Answer directly — don't delegate exploration.** For "how does X work" / architecture questions, answer with 2-3 codegraph calls: `codegraph_context` first, then ONE `codegraph_explore` for the source of the symbols it surfaces. For a specific **flow** ("how does X reach Y") start with `codegraph_trace` from→to — one call returns the whole path with dynamic hops bridged — then ONE `codegraph_explore` for the bodies; don't rebuild the path with `codegraph_search` + `codegraph_callers`. Codegraph IS the pre-built index, so spawning a separate file-reading sub-task/agent — or running a grep + read loop — repeats work codegraph already did and costs more for the same answer.
- **Trust codegraph results.** They come from a full AST parse. Do NOT re-verify them with grep — that's slower, less accurate, and wastes context.
- **Don't grep first** when looking up a symbol by name. `codegraph_search` is faster and returns kind + location + signature in one call.
- **Don't chain `codegraph_search` + `codegraph_node`** when you just want context — `codegraph_context` is one call.
- **Don't loop `codegraph_node` over many symbols** — one `codegraph_explore` call returns several symbols' source grouped in a single capped call, while each separate node/Read call re-reads the whole context and costs far more.
- **Index lag**: the file watcher debounces ~500ms behind writes; don't re-query immediately after editing a file in the same turn.

### If `.codegraph/` doesn't exist

The MCP server returns "not initialized." Ask the user: *"I notice this project doesn't have CodeGraph initialized. Want me to run `codegraph init -i` to build the index?"*
<!-- CODEGRAPH_END -->

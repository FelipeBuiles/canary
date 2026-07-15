# Canary — Agent Guidelines

Compact instruction file for every coding-agent session. Detailed reference:
`docs/reference/agent-context.md`.

## Project Snapshot

Canary is a Python/React app that turns novels into comic books via a 9-stage
pipeline. Each stage is discrete, resumable, and produces inspectable JSON/file
output. The pipeline is orchestrated through a FastAPI web server — there is no
`pipeline run` CLI command. Use the web UI or call the API directly.

**Brand & GTM:** "Canary" is the internal codename. Recommended launch name is
**`Scenewright`** (`scenewright.ink`), chosen for an AI-hostile indie-author
audience. Full naming research, competitive/market analysis, and lean-tier
go-to-market plan: `docs/proposals/branding-and-marketing.md`.

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

**UI stations (frontend grouping only):** The web UI presents the 9 backend
stages as 4 user-facing "stations" (implemented June 2026). Backend stages stay
discrete — stations are presentation/navigation only, never backend
consolidation. Plan + status: `docs/proposals/four-station-redesign.md`.

| Station | Backend stages | User gate |
|---|---|---|
| 01 Story | `extract` | approve extract |
| 02 Look | `style`, `cast` | select style; approve cast (kicks the auto chain) |
| 03 Panels | `adapt`→`plan`→`storyboard`→`direct` (auto, inspectable), `draw` | run draw; flag-by-exception review; approve draw |
| 04 Book | `compose` | export |

Auto stages never block: they run as a chain after cast approval and surface
as read-only inspect drawers (placeholder shown if not yet generated). Stage
order is unchanged — do not reorder stages for the UI.

Key invariants of the implemented redesign:

- `CHECKPOINT_STAGES = {extract, style, cast, draw}` — `direct` is no longer a
  checkpoint. Prompt editing happens per-panel in the panel detail modal.
- Panel review is flag-by-exception: panels are accepted by default; flags
  (`draw/panel_flags.json`) never block compose. "Accept all — Continue"
  approves the `draw` stage. Per-panel acceptance endpoints still exist but
  the UI no longer surfaces them.
- Every gated room ends in the shared `ApprovalBar` (fixed bottom of content);
  the sidebar has no CTA. Credits phrasing is `~N credits` everywhere — never
  "Est. N" or "reserves up to N".
- Dev Content defaults OFF. Machine vocabulary (entity IDs, hashes, model
  names) and the old adapt/shot-plan/direct rooms are gated behind it.

**Current focus:** post-redesign hardening (issues auto-fixes, es/fr copy for
the new EN strings), draw-stage image review quality, and credits/billing
accuracy.

## Must-Know Rules

- **No `pipeline run` CLI.** Pipeline operations (run, approve, status, export)
  are HTTP API endpoints on the web server. The CLI only has `init` and `serve`.
  See `novel_to_comic/src/novel_to_comic/server/routers/pipeline.py` for all pipeline endpoints.
- Do not collapse stages or add cross-stage logic. Each stage reads its inputs
  from disk and writes its own outputs. The 4-station UI grouping lives entirely
  in the frontend (`web/src/lib/uiStages` and SideNav) — never in stage code.
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
- **Image model routing:** `image-quality` routes to Gemini 3 Pro Image
  (Nano Banana 2 Pro) via the vertex-multimodal handler; only `image-reve`
  routes to Reve (`REVE_ALIASES`). `GPT_IMAGE_2_ALIASES` is now empty —
  `is_gpt_image_2()` only matches literal `gpt-image-2` strings, not gateway
  aliases.
- **Panel aspect:** All aspect-ratio → dimension logic lives in `panel_aspect.py`
  (`GenerationShape`, `dimensions_for_generation_aspect`, `aspect_within_tolerance`).
  Do not inline dimension math in stage or route code.

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
- Panel aspect/shape helpers: `novel_to_comic/src/novel_to_comic/panel_aspect.py`
- Panel record CRUD (s5→s9): `novel_to_comic/src/novel_to_comic/panel_store.py`
- Layout planning models + helpers: `novel_to_comic/src/novel_to_comic/layout_planning.py`
- Narration decision editing: `novel_to_comic/src/novel_to_comic/server/narration_editor.py`
- Assembly renderer: `novel_to_comic/src/novel_to_comic/assembly/html_renderer.py`
- Comic editing models: `novel_to_comic/src/novel_to_comic/models/comic_page.py`
- Panel acceptance state: `novel_to_comic/src/novel_to_comic/server/panel_acceptance.py`
- Panel re-work flags (review-by-exception): `novel_to_comic/src/novel_to_comic/server/panel_flags.py`
- Primary cast ref selection: `read_primary_refs`/`write_primary_refs` in `novel_to_comic/src/novel_to_comic/artifacts.py`
- Station ↔ stage mapping (frontend): `web/src/lib/stations.ts`
- Standing approval bar: `web/src/components/composites/ApprovalBar.tsx`
- Auto-step inspect drawers: `web/src/components/InspectDrawer.tsx`
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


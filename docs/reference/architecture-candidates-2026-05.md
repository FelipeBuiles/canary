# Architecture Deepening Candidates — May 2026 Round

> **Historical document.** All candidates in this round have been implemented.
> The shipped modules are: `stage_runtime.py` (C1), `panel_store.py` (C2/C4 partial),
> `server/credited_job.py` (C4), `prompt_assembly.py` (C5),
> `server/narration_editor.py` (C6). C3 (image provider seam) was resolved by
> keeping the existing structure. Refer to `CONTEXT.md` and
> `docs/reference/agent-context.md` for current architecture.

Second-pass architecture survey. Read alongside
[`architecture-candidates.md`](architecture-candidates.md), which tracks the
April 2026 round.

This document uses the vocabulary from
`~/.claude/skills/improve-codebase-architecture/LANGUAGE.md`:

- **Module** — interface + implementation.
- **Interface** — everything a caller must know (types, invariants, ordering, error modes, config).
- **Depth** — leverage per unit of interface. Deep = a lot of behaviour behind a small interface.
- **Seam** — where an interface lives.
- **Adapter** — a concrete thing satisfying an interface at a seam.
- **Deletion test** — if you deleted the module, does complexity vanish (shallow) or reappear across N callers (deep)?
- **One adapter = hypothetical seam. Two adapters = real seam.**

There is no `CONTEXT.md` and no `docs/adr/` directory yet, so the domain terms
used below are drawn from `AGENTS.md` and `docs/reference/agent-context.md`:
stage, Story Bible, panel, screenplay, layout plan, panel breakdown, image
prompt, narration decision, compose.

## How this round relates to the April 2026 round

| April candidate | Status | This round |
|---|---|---|
| C1 Artifact Path Module | Done | Confirmed deep — left alone. |
| C2 Stage Protocol + Registry | Done | The **registry** half is done; the **runtime/lifecycle** half (events, usage, state) is not. See [May C1](#may-c1--stage-runtime). |
| C3 Typed Event Schema | Open | Subsumed by [May C1](#may-c1--stage-runtime) — if we deepen the runtime, the event type lives inside the runtime module's interface, not as a standalone schema. |
| C4 Character Identity Seam | Open | Independent — proceed as planned. |
| C5 Job Queue / Stage State Integration | Open | Re-framed as [May C4](#may-c4--credited-job) — the friction is the *credit + job lifecycle coupling*, not just typed payloads. The April framing is correct as far as it goes; this round goes one level deeper. |

The remaining candidates below are **new**.

---

## May C1 — Stage runtime

**Files involved**

- `novel_to_comic/state.py` — `begin_stage`, `record_item_done`, `record_api_usage`, `complete_stage`, `fail_stage`, `STAGE_NAMES`
- `novel_to_comic/events.py` — `EventCallback`, ad-hoc dict events
- `novel_to_comic/stages/__init__.py` — `STAGE` dataclass + `REGISTRY` (April C2)
- All `stages/s1..s8_*.py` (s5 prefix appears twice; `direct` lives in `s6_storyboard.py` per AGENTS.md)

**Problem**

The April round gave stages a shared *registration* surface (`STAGE` + `REGISTRY`).
It did not give them a shared *runtime*. Every stage still re-implements the
same lifecycle skeleton by hand:

1. Call `begin_stage(state, name, total)`.
2. Emit progress events through `on_event` next to every `console.print()`.
3. Call `record_item_done` / `record_api_usage` per iteration.
4. Call `complete_stage` on success or `fail_stage` on exception.

`on_event` is threaded into every stage signature for one reason: each stage
manually calls it. `STAGE_NAMES` is a string list duplicated in `state.py`.

**Deletion test**

Delete the per-stage lifecycle calls and the manual `emit()` ceremony. The
logic reappears nine times — a deep-module signal — but the module that should
own it doesn't exist. Today the leverage is zero; the locality is zero (a
change to event semantics or counter semantics touches every stage file).

**Sketch**

A module that owns the lifecycle of a single stage execution. It takes the
stage's pure work as input, owns event emission, usage recording, state
transitions, and error mapping. Stages shrink to "given inputs, produce
outputs"; they no longer thread `on_event` or know about `State` mutation.

This supersedes April C3 (Typed Event Schema): the typed event becomes part
of this module's interface rather than a standalone surface.

**Test consequence**

- Per-stage tests stop asserting on event sequences.
- One test exercises the lifecycle module against a fake stage and verifies
  begin → progress×n → complete and the error path.
- Stage tests become "given inputs, produce outputs."

**Dependencies**

Builds on April C2 (`STAGE` + `REGISTRY`). Subsumes April C3 — do not
implement C3 separately.

---

## May C2 — Panel evolution

**Files involved**

- `models/panel.py` — `PanelBreakdown`
- `models/prompt.py` — `ImagePrompt`
- `models/layout_plan.py` — `PlannedPanel`
- `models/comic_page.py` — `PagePanel`, `ComicPage`
- `layout_planning.py` (747 lines)
- `stages/s5_layout_plan.py` (1639 lines), `s6_storyboard.py`, `s7_draw.py` (`direct`), `s8_compose.py`
- `panel_versions.py`
- `server/routers/stages.py`, `server/routers/pages.py` — patch panel JSON in place

**Problem**

A single panel is described by five overlapping models as it moves through
stages 5 → 9. Every reader needs to know which schema is current at which
stage, what the previous stage wrote, and which override paths apply.

The "panel as it evolves" lives smeared across stage files and routers:

- `routers/stages.py` reads `PanelBreakdown` JSON, patches it, re-validates,
  re-writes — duplicating logic the layout planner already partly owns.
- `layout_planning.py` is a bucket of ~10 helpers callers compose by hand
  (see s5_layout_plan.py chaining roughly ten of them in sequence).

**Deletion test**

Delete `layout_planning.py` and the logic splinters across caller sites — so
*something* is earning its keep. But the current interface ("here are the
helpers, you stitch them") is nearly as complex as the implementation. The
seam is in the wrong place.

**Sketch**

A module that owns the panel record across its lifecycle: read from disk at
the right version, apply structured overrides, hand back the next-stage
shape. Routes dispatch into it instead of editing JSON in place.

The exact shape — class with explicit state transitions, or a module of
functions over a single union type — is a grilling decision.

**Test consequence**

- Most JSON-patching tests in `routers/stages.py`-adjacent test files become
  tests of the new module's interface.
- A single integration test walks s6 → s8 in-memory without touching disk.
- Panel-validity logic (currently `_draw_panel_blockers_for_compose` in the
  pipeline router per April C2 history) has a natural home.

**Dependencies**

Benefits from May C1 (stage runtime) being in place so the new module isn't
re-entangled with event/usage plumbing.

---

## May C3 — Image provider seam (ceremony vs. real seam)

**Files involved**

- `ai/providers/base.py` — `ImageProvider` Protocol
- `ai/providers/selector.py` — `pick()`
- `ai/providers/litellm_http.py` — sole production adapter
- `clients/flux.py` — wraps the provider

**Problem**

The Protocol promises swappability. `selector.pick()` is hard-coded to return
`LitellmHttpProvider()` and ignores its arguments. There is one production
adapter, no test adapter, and `clients/flux.py` adds a third layer of
indirection on top.

**One adapter = hypothetical seam.** This is the canonical case.

**Deletion test**

Collapsing the Protocol, the selector, and `clients/flux.py` into a single
module removes three indirections without changing behaviour. The
"abstraction" is currently paying no callers back.

**Sketch**

Two valid responses; the grilling decides which:

1. **Collapse.** Delete the Protocol and selector. Inline LitellmHttp into
   `flux.py` until a second adapter is genuinely needed. Defers the
   abstraction cost until leverage emerges.
2. **Deepen.** Introduce a real second adapter — an in-memory fake used by
   image-stage tests — so the seam earns its keep today.

Either is valid. The wrong answer is what's there now: a Protocol that
nothing varies across.

**Test consequence**

- *Collapse:* `test_ai_client.py` mocks shrink; production code is one
  fewer hop.
- *Deepen:* image-stage tests stop hitting the network because the fake
  adapter is the test-time concrete implementation.

**Dependencies**

Independent. Cheapest decision in the queue — worth resolving early so the
answer informs how other one-adapter seams (if any) are treated.

---

## May C4 — Credited job

**Files involved**

- `server/credits.py` — reservation/debit/release logic
- `server/generation_jobs.py` — in-memory job queue
- `server/routers/pipeline.py` — `regen_panel`, `regen_ref`, `regen_plate`, `regen_prop` handlers

**Problem**

Four router handlers each repeat the same dance:

1. Assert credits.
2. Enqueue a job.
3. On success in the runner, debit.
4. On failure, release (this branch lives in a route-level `except` block).

Credits and jobs are each independently coherent. Their *coupling* is not
localised — it lives in HTTP handlers. The April round (C5) identified the
job/state integration problem and proposed typed payloads. The deeper
friction is that the *credit guarantee* itself has no module.

**Deletion test**

The coupling reappears in every regen handler. That's the signal — a deep
module is missing here.

**Sketch**

A module that owns "a job with a credit guarantee" — reserve on enqueue,
debit on success, release on failure, in one place. Handlers shrink to
payload assembly + dispatch.

Subsumes most of April C5: typed payloads are still wanted, but they ride
inside the credited-job module's interface rather than being threaded
through the job queue independently.

**Test consequence**

- Four near-duplicate handler tests collapse into one module-level test that
  covers reserve / debit / release.
- Tests don't need a TestClient to verify the credit guarantee.

**Dependencies**

Refines April C5. Do not implement C5 separately.

---

## May C5 — Prompt composition

**Files involved**

- `prompting.py` (~50 helpers, 1182 lines)
- `prompt_instructions.py`
- `stages/s7_draw.py` (the `direct` stage)
- `server/routers/stages.py` — `update_prompt` rebuilds prompts on edit

**Problem**

`prompting.py` is a flat bag of pure functions: `_shot_dimensions`,
`_planned_panel_text_pieces`, `_distilled_subject_clause`, etc. Composition
lives in two places:

- `build_planned_panel_prompt_spec()` — used by the `direct` stage
- `render_panel_prompt_body()` — used by the route that re-renders on edit

Each helper is tested in `test_prompting.py`. The composition is not.

This is the classic "pure functions extracted for testability, but the bugs
hide in how they're called" pattern. Locality is zero — drift between the
two composition sites is the bug class waiting to happen.

**Deletion test**

Refactoring the bag of helpers into ten smaller files wouldn't change
behaviour — only the call sites would shuffle. That's the shallow signal.

**Sketch**

A module that owns prompt assembly end-to-end for a panel. Helpers can stay
private to its implementation; the public interface is roughly
`(PlannedPanel, StoryBible, config) → ImagePrompt`. Both `direct` and the
edit route call the same path, making drift impossible.

**Test consequence**

- Many tiny `test_prompting.py` tests either delete or move behind the new
  module's interface.
- A composition-level test verifies that editing a prompt and re-rendering
  doesn't lose fields.

**Dependencies**

Interacts with April C4 (Character Identity Seam): identity strings would
become part of this module's internal composition, not separate helpers
that callers stitch in. Recommend doing C4 first so the identity rule is
already localised, then folding it into C5.

---

## May C6 — Narration decision editing

**Files involved**

- `models/layout_plan.py` — `NarrationDecision`
- `layout_planning.py` — `apply_narration_decision_patch`, `classify_narration_change_impact`
- `server/routers/stages.py` — narration-edit and impact-estimate endpoints

**Problem**

Editing a narration decision requires three modules to cooperate:

- Schema lives in `models/`.
- Patch + impact classification lives in `layout_planning.py`.
- Cost estimation and persistence lives in the route.

To test "what happens when I change this decision" you must go through a
FastAPI handler.

**Deletion test**

This exact composition would reappear at the next narration-related edit
feature — so the deep module is missing.

**Sketch**

A module that owns load → apply patch → classify impact → estimate cost →
save, returning the bundle to the route. The route becomes a thin
dispatcher.

**Test consequence**

- Impact-estimation tests stop going through FastAPI.
- One module-level test, multiple scenarios.

**Dependencies**

Mostly independent. Touches the same files as May C2 (Panel evolution); if
both ship, do C2 first so the narration editor reads/writes through the
same lifecycle module.

---

## Modules confirmed deep (do not re-litigate)

- **`state.State`** — compact interface, substantial implementation, good
  locality. (April round already validated; still true.)
- **`artifacts`** — April C1, done; still earning its keep.
- **`config`** load/save — single load point.

---

## Suggested order

| # | Candidate | Depends on | Notes |
|---|---|---|---|
| 1 | May C3 — Image provider seam | — | Cheap decision; resolve first. |
| 2 | May C1 — Stage runtime | April C2 (done) | Highest locality payoff. Subsumes April C3. |
| 3 | April C4 — Character identity | — | Small, independent. Sets up C5. |
| 4 | May C5 — Prompt composition | April C4 | Folds identity into a single assembly module. |
| 5 | May C4 — Credited job | — | Refines April C5; do not ship C5 separately. |
| 6 | May C2 — Panel evolution | May C1 | Largest scope; benefits from runtime cleanup first. |
| 7 | May C6 — Narration decision editing | May C2 | Smaller follow-on to C2. |

---

## Open process notes

- This repo has no `CONTEXT.md` or `docs/adr/` directory. If any of these
  candidates get grilled and rejected with a load-bearing reason, that's
  the moment to start an `docs/adr/` tree so future surveys don't
  re-suggest the same thing.
- If any deepened module gets named after a concept not already in
  `AGENTS.md` or `docs/reference/agent-context.md`, capture the term in a
  new `CONTEXT.md` at the repo root.

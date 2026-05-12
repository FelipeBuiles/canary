# Architecture Deepening Candidates

Outcome of the April 2026 architecture review. Candidate 1 (Artifact Path
Module) and Candidate 2 (Stage Protocol + Registry) are complete — see
`novel_to_comic/artifacts.py` and `novel_to_comic/stages/__init__.py`. This
document covers the remaining candidates and the historical reasoning behind
completed ones.

---

## Candidate 2 — Stage Protocol + Registry

**Files involved**
- `server/routers/pipeline.py` — registry dispatch and rerun cleanup
- `stages/s1_extract.py` through `s8_compose.py`

**Original problem (now addressed)**

Stages are plain async functions with no shared interface. The pipeline router
compensates by hardcoding three parallel dicts that must stay in sync:

- `_stage_runner` — how to invoke each stage
- `_STAGE_OUTPUTS` — what file each stage produces (used to detect stale completions)
- `_RERUN_CLEAN_PATHS` — directories to delete on rerun

Each new stage requires editing the router in at least three places. Stage 7's
panel-validity logic (`_draw_panel_blockers_for_compose`) also lives in the
router despite being stage-specific knowledge.

**Solution**

Define a `Stage` dataclass (or Protocol) in `stages/__init__.py`:

```python
@dataclass
class Stage:
    name: str
    run: Callable  # async def run(config, project_dir, state, on_event) -> Any
    outputs: Callable[[Path], list[Path]]       # what this stage produces
    clean_paths: Callable[[Path], list[Path]]   # what to delete on rerun
```

Each stage module exposes a `STAGE` sentinel:

```python
# stages/s1_extract.py
STAGE = Stage(
    name="extract",
    run=run,
    outputs=lambda d: [artifacts.story_bible_path(d), d / "scenes"],
    clean_paths=lambda d: [artifacts.story_bible_path(d), d / "scenes", d / "refs", d / "plates"],
)
```

A registry in `stages/__init__.py` maps name → stage:

```python
REGISTRY: dict[str, Stage] = {s.STAGE.name: s.STAGE for s in [s1_extract, s2_style, ...]}
```

The router becomes a thin dispatch:

```python
stage = REGISTRY[stage_name]
runner = lambda on_event: stage.run(config, project_dir, state, on_event=on_event)
```

Stale-completion checks use `stage.outputs(project_dir)`. Rerun cleanup uses
`stage.clean_paths(project_dir)`. The router no longer knows anything about
individual stages.

**Benefits**

- **Locality**: adding a stage is one file change. The router needs no edits.
- **Leverage**: `outputs()` and `clean_paths()` are the test surface for stage
  contracts. A test can assert `STAGE.outputs(project_dir)` without running the
  stage.
- **Deletion test**: delete `_stage_runner`, `_STAGE_OUTPUTS`, `_RERUN_CLEAN_PATHS`
  from the router — complexity reappears in the `STAGE` sentinels, not scattered
  across callers.

**Dependencies**: benefits from Candidate 1 (Artifact Path Module) being in
place so `outputs()` and `clean_paths()` can call `artifacts.*` rather than
building paths inline.

---

## Candidate 3 — Typed Event Schema

**Files involved**
- `novel_to_comic/events.py`
- All 9 stage files (emit calls)
- `server/routers/pipeline.py` (emits `pipeline_done`, `stage_fail`)

**Problem**

Events are `dict[str, Any]` with string keys. A typo (`"typ"` vs `"type"`,
wrong counter value) produces silent incorrect behavior in the web UI. Stage
files emit ~15 events each, all hand-constructed. The router emits a parallel
event stream from a different code path. There is no schema validation at
emit time.

Example of current fragility:

```python
emit({"type": "stage_progress", "stage": "extract", "done": 3, "total": 4})
# vs. a typo:
emit({"type": "stage_progres", "stage": "extract", "done": 3, "total": 4})
# → silently dropped by client
```

**Solution**

Replace the dict with a typed discriminated union in `events.py`:

```python
@dataclass(frozen=True)
class StageBeginEvent:
    stage: str
    total: int
    type: str = "stage_begin"

@dataclass(frozen=True)
class StageProgressEvent:
    stage: str
    done: int
    total: int
    type: str = "stage_progress"

@dataclass(frozen=True)
class StageCompleteEvent:
    stage: str
    done: int
    total: int
    type: str = "stage_complete"

@dataclass(frozen=True)
class StageFailEvent:
    stage: str
    message: str
    type: str = "stage_fail"

@dataclass(frozen=True)
class LogEvent:
    stage: str
    level: Literal["info", "warn", "error", "dim", "bold"]
    message: str
    type: str = "log"

PipelineEvent = StageBeginEvent | StageProgressEvent | StageCompleteEvent | StageFailEvent | LogEvent
EventCallback = Callable[[PipelineEvent], None]
```

The SSE serialization layer converts to dict/JSON at the boundary. Stages
call `emit(StageProgressEvent(stage="extract", done=3, total=4))`.

A migration helper can accept both old dicts and new typed events during
transition:

```python
def emit_event(on_event: EventCallback | None, event: PipelineEvent) -> None:
    if on_event is not None:
        on_event(event)
```

**Benefits**

- **Interface as test surface**: tests can `assert isinstance(events[0], StageBeginEvent)` 
  and check `.total` directly.
- **Locality**: every event shape is defined in one file. Adding a field to
  `StageProgressEvent` is one edit, not a grep across 9 stage files.
- **Leverage**: typos become type errors at emit time, not silent client-side
  drops.

**Dependencies**: independent — can be done before or after Candidates 2 and 4.

---

## Candidate 4 — Character Identity Seam

**Files involved**
- `models/story_bible.py` — `Character` model (`visual_anchor`, `distinguishing_features`, etc.)
- `stages/s3_cast.py` — `_character_ref_prompt()`, `_cast_identity_lock()`
- `stages/s6_storyboard.py` — `PromptSubject.identity` (via `build_planned_panel_prompt_spec`)
- `novel_to_comic/prompting.py` — `build_planned_panel_prompt_spec()`
- `stages/s7_draw.py` — upgrades old prompts from `visual_anchor` when needed

**Problem**

"Character identity" — how a `Character`'s visual attributes are encoded into
prompt text — is computed independently by three stages, each producing a
different encoding:

- **S3** (`_character_ref_prompt`): combines style, identity lock, visual anchor, and outfit details for casting reference sheets
- **S6** (`build_planned_panel_prompt_spec` → `PromptSubject`): `identity = "{visual_anchor}, {features}, {outfit}"` — used for panel image prompts
- **S7**: upgrades legacy prompt artifacts from `visual_anchor` when prompt specs are missing planner-era fields

The `visual_anchor` contract — *"injected verbatim at the very start of identity"* — is documented in `AGENTS.md` but enforced nowhere. If the rule changes (e.g., visual_anchor must come after a style prefix), three code paths need updating.

**Solution**

A `novel_to_comic/character_identity.py` module with named representations:

```python
def as_reference_signature(char: Character) -> str:
    """Identity string for S3 casting — used in reference sheet prompts."""
    features = ", ".join(clean(f) for f in char.distinguishing_features[:4])
    pieces = [f"{char.name}: {clean(char.age_range)} {clean(char.gender)}", features, clean(char.default_outfit)]
    return shorten("; ".join(p for p in pieces if p), 220)

def as_prompt_identity(char: Character) -> str:
    """Identity string for S6/S7 panel prompts — visual_anchor injected verbatim first."""
    parts = [char.visual_anchor]
    if char.distinguishing_features:
        parts.append(", ".join(char.distinguishing_features[:3]))
    if char.default_outfit:
        parts.append(clean(char.default_outfit))
    return ", ".join(p for p in parts if p)
```

Stages call these instead of building identity strings inline. The
`visual_anchor`-first invariant is enforced in `as_prompt_identity`, not
assumed by callers.

**Benefits**

- **Locality**: character visual consistency bugs concentrate in one module.
- **Leverage**: callers get correct identity strings without knowing the
  `visual_anchor` injection rule.
- **Test surface**: `as_prompt_identity` can be tested directly against
  `Character` fixtures — no stage execution needed.
- **Deletion test**: delete inline cast identity construction from S3 and
  prompt identity construction from S6 — complexity reappears in one place.

**Dependencies**: independent. The `visual_anchor` verbatim rule is an invariant
worth capturing in `CONTEXT.md` when this is implemented.

---

## Candidate 5 — Job Queue / Stage State Integration

**Files involved**
- `server/generation_jobs.py` — `GenerationJob`, `enqueue_generation_job()`, `generation_worker()`
- `state.py` — `PipelineState`, `StageState`
- `server/routers/pipeline.py` — panel regen endpoints
- `stages/s7_draw.py` — `regenerate_panel_image()`

**Problem**

Two parallel execution models exist that don't share state:

1. **Main pipeline** — stages run sequentially via `/run`, update `PipelineState`.
2. **Targeted regeneration** — individual panel rerenders via `GenerationJob` queue.

When a `GenerationJob` completes, it calls `s7_draw.regenerate_panel_image()`
directly and debits model usage, but does not update `PipelineState.stages["draw"]`
as if a normal stage item completed. The web UI must poll status/images and
`/generation-jobs` to assemble a full picture. Job
payloads are untyped `dict[str, Any]` — the router builds them and the runner
destructures them with no shared type enforcing the contract.

```python
# Router constructs:
payload={"scene_id": scene_id, "panel_number": panel_number, "instruction": instruction}

# Runner assumes:
runner=lambda: s7_draw.regenerate_panel_image(
    config, project_dir,
    scene_id=scene_id, panel_number=panel_number,
)
# No validation that payload keys match runner kwargs.
```

**Solution**

Define a typed `PanelRegenerationRequest`:

```python
@dataclass(frozen=True)
class PanelRegenerationRequest:
    scene_id: str
    panel_number: int
    instruction: str | None = None
```

`enqueue_generation_job` gains a `request` parameter typed to the job kind's
dataclass. The runner is constructed from the typed request, not from a raw dict.

Wire job completion back to `PipelineState`: when `regenerate_panel` succeeds,
call `record_item_done(state, "draw", ...)` so the draw stage's counters and
cost reflect all regenerations, not just the initial pipeline run.

Unify the status query: `/api/projects/{project}/status` includes job-level
status for in-progress panel regenerations alongside stage state.

**Benefits**

- **Locality**: payload shape and runner kwargs are the same typed object.
  Mismatches are type errors.
- **Single source of truth**: the web UI reads one endpoint for all pipeline
  state including in-flight regenerations.
- **Leverage**: `record_item_done` accumulates real cost for targeted rerenders,
  making cost reporting accurate across the full project lifetime.

**Dependencies**: benefits from Candidate 2 (Stage Protocol) being in place so
the job queue can call `REGISTRY["draw"].regenerate(request)` instead of
importing the stage module directly.

---

## Implementation Order

| # | Candidate | Depends on | Effort |
|---|-----------|-----------|--------|
| 1 | Artifact Path Module | — | **Done** |
| 2 | Stage Protocol + Registry | 1 | Medium |
| 3 | Typed Event Schema | — | Small |
| 4 | Character Identity Seam | — | Small |
| 5 | Job Queue / Stage State Integration | 2 | Medium |

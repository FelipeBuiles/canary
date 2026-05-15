# Draw Stage Liveness & Live Cockpit Design

**Date:** 2026-05-15
**Status:** Approved

## Overview

The Draw Panels stage today shows pending panels as `STALE` after a 5-minute wall-clock since `started_at`, even when the asyncio task is happily generating panels in the background. The cause is a naive heuristic in `state.is_stale()` that ignores actual liveness signals, plus a frontend rule (`DrawRoom.tsx`, `panelState.ts`) that propagates stage-level "stale" onto every pending panel. REST `/status` polls re-inject `stale: true` every 2s, clobbering SSE's `stale: false` updates.

This design replaces the wall-clock heuristic with three independent liveness signals (per-stage heartbeat, live-task ground truth, per-panel events), removes "stale" as a per-panel concept, and rebuilds the Draw Room right rail as a live cockpit that surfaces what's in flight, what just finished, throughput, ETA, and per-scene progress.

---

## Problem Statement

| Issue | Current Behavior |
|-------|------------------|
| **Wall-clock stale check** | `is_stale = RUNNING and (now - started_at) > 5min` — fires on every healthy long draw run |
| **Stale leaks to panels** | `DrawRoom.tsx:303` overrides every pending panel to `stale` when stage is stale |
| **REST clobbers SSE** | `/status` poll re-computes `stale: true` every 2s; SSE's `stale: false` updates lose the race |
| **No per-panel events** | Only aggregate `stage_progress` (done/total) — no signal for which panels are in flight or just finished |
| **`isDrawRunning` over-marks** | Every pending panel renders as `GENERATING…` whenever the stage is running, regardless of whether it's actually in flight |
| **Tab-switch surfacing** | React Query pauses polling on hidden tabs; on focus, the first REST poll surfaces the wall-clock-stale flag |
| **Right-rail clutter blocks live info** | The credits estimate and generation options cards occupy rail space that should report on the run |

---

## Section 1 — Backend: Liveness Model

### 1a. Per-stage heartbeat (`StageState.last_progress_at`)

Add to `StageState` in `novel_to_comic/src/novel_to_comic/state.py`:

```python
class StageState(BaseModel):
    ...existing fields...
    last_progress_at: Optional[datetime] = None
```

Update it in `record_item_done` and `record_api_usage`:

```python
def record_item_done(state, stage, cost=0.0, usage=None):
    ...
    s.last_progress_at = datetime.now(timezone.utc)

def record_api_usage(state, stage, usage):
    ...
    s.last_progress_at = datetime.now(timezone.utc)
```

Rewrite `is_stale`:

```python
STALE_RUNNING_THRESHOLD = timedelta(minutes=5)

def is_stale(stage_state: StageState) -> bool:
    if stage_state.status != StageStatus.RUNNING:
        return False
    last = stage_state.last_progress_at or stage_state.started_at
    if last is None:
        return False
    return datetime.now(timezone.utc) - last > STALE_RUNNING_THRESHOLD
```

`begin_stage` should reset `last_progress_at = None` (so a fresh run doesn't inherit the prior heartbeat).

### 1b. Running-task as ground truth

In `novel_to_comic/src/novel_to_comic/server/routers/projects.py:_stage_payload`, AND the heartbeat check with the live task check:

```python
def _stage_payload(project_dir, name, state, *, is_running_task: bool):
    ...
    return {
        ...,
        "stale": is_stale(s) and not is_running_task,
    }
```

The caller (`project_status`) already computes `running` via `_is_project_running`. Pass it down. The wall-clock heuristic now only fires when state.json says RUNNING but no live task exists (server restart).

### 1c. Per-panel events

Two new event types in `novel_to_comic/src/novel_to_comic/events.py` (the schema is dict-shaped, no Pydantic model — extend the docstring):

```jsonc
{ "type": "panel_start", "stage": "draw",
  "scene_id": "scene_03", "panel_number": 7,
  "started_at": "2026-05-15T18:42:11Z" }

{ "type": "panel_done",  "stage": "draw",
  "scene_id": "scene_03", "panel_number": 7,
  "status": "ok" | "failed",
  "duration_ms": 14320,
  "error": null | "..." }
```

Emit them inside `_generate_panel` in `novel_to_comic/src/novel_to_comic/stages/s7_draw.py` — at semaphore acquire, and in `finally` blocks for both success and failure paths. Threaded via the existing `ctx.on_event` (passed through from `run`).

Add a thin helper on `StageRuntime`:

```python
def emit_panel_start(self, scene_id: str, panel_number: int, started_at: datetime) -> None:
    self._emit({"type": "panel_start", "stage": self.name,
                "scene_id": scene_id, "panel_number": panel_number,
                "started_at": started_at.isoformat()})

def emit_panel_done(self, scene_id: str, panel_number: int,
                    status: str, duration_ms: int, error: str | None = None) -> None:
    self._emit({"type": "panel_done", "stage": self.name,
                "scene_id": scene_id, "panel_number": panel_number,
                "status": status, "duration_ms": duration_ms, "error": error})
```

### 1d. In-flight set in status payload

Server-side, maintain a per-project in-memory map of in-flight panels (no disk persistence — if the server restarts, nothing is in flight by definition).

Location: extend `app.state` with a dict:

```python
app.state.draw_in_flight: dict[str, list[InFlightPanel]] = {}
# keyed by project_key(user_id, project_id)
```

**How it's populated without leaking FastAPI into stage code.** The pipeline runner that calls `stage.run(ctx)` already wraps the stage's `on_event` callback to fan out to SSE subscribers. Extend that wrapper so when the event is `panel_start` / `panel_done`, it *also* mutates `app.state.draw_in_flight[pkey]`. The stage code stays unaware of `app.state` — it only emits events. State.py / stage_runtime.py stay framework-agnostic.

The `/status` endpoint reads from the map for the `in_flight` field on the draw stage payload:

```jsonc
"draw": {
  ...,
  "stale": false,
  "last_progress_at": "2026-05-15T18:42:11Z",
  "in_flight": [
    { "scene_id": "scene_03", "panel_number": 7,
      "started_at": "2026-05-15T18:42:11Z" }
  ]
}
```

Cleared when the stage completes / fails / on server restart.

---

## Section 2 — Frontend: State Model

### New types (`web/src/types/api.ts`)

```ts
export interface InFlightPanel {
  scene_id: string;
  panel_number: number;
  started_at: string;
}

export interface PanelStartEvent {
  type: "panel_start";
  stage: string;
  scene_id: string;
  panel_number: number;
  started_at: string;
}

export interface PanelDoneEvent {
  type: "panel_done";
  stage: string;
  scene_id: string;
  panel_number: number;
  status: "ok" | "failed";
  duration_ms: number;
  error: string | null;
}

// StageInfo gets:
//   last_progress_at: string | null;
//   in_flight: InFlightPanel[];
```

`PipelineEvent` union extends to include `PanelStartEvent` and `PanelDoneEvent`.

### New Zustand slice (`web/src/store/drawProgress.ts`)

```ts
interface DrawProgressSlice {
  inFlight: Map<string, { startedAt: number }>;       // key = `${sceneId}-${panelNumber}`
  recentFinishes: RingBuffer<10, FinishRecord>;
  hydrate(stage: StageInfo): void;                     // from /status
  applyPanelStart(e: PanelStartEvent): void;
  applyPanelDone(e: PanelDoneEvent): void;
  clear(): void;                                       // on stage_complete / stage_fail / pipeline_done
}
```

Derived selectors:
- `useInFlightSorted()` — sorted by elapsed desc (longest-running first).
- `useThroughputPerMin()` — finishes in the last 60s.
- `useEta(itemsRemaining)` — `itemsRemaining / throughput`, returns `null` while `recentFinishes.size < 3`.

Hydrated from `/status` on first load (so a fresh page render has live data) and maintained from SSE events thereafter.

### New `PanelDisplayState` (`web/src/lib/panelState.ts`)

```ts
export type PanelDisplayState =
  | "pending"
  | "queued"        // NEW: in this run's target set, not yet started
  | "generating"    // in flight (in inFlight set) OR explicit regen running
  | "generated"
  | "regenerated"
  | "accepted"
  | "failed";       // "stale" REMOVED
```

Updated logic:

```ts
export function getPanelDisplayState(
  img,
  regenMode,          // "queued" | "running" | null
  inFlight,           // boolean — is this panel in inFlight set
  isQueuedInRun,      // boolean — is this panel in the current run target
): PanelDisplayState {
  if (img.accepted) return "accepted";
  if (regenMode === "running" || inFlight) return "generating";
  if (regenMode === "queued") return "queued";
  if (img.status === "failed") return "failed";
  if (img.status === "done") return (img.version_count ?? 0) > 1 ? "regenerated" : "generated";
  if (isQueuedInRun) return "queued";
  return "pending";
}
```

`isQueuedInRun` is derived in `DrawRoom`: `stageRunning && image is in stage's target set && !inFlight && !done && !failed`.

For the v1 implementation, "stage's target set" can be approximated as "every pending image when no `panel_numbers`/`scene_ids` filter is set" — matching today's heuristic that `isDrawRunning` implies all pendings are in the run. A future improvement (out of scope for this spec) is to expose the actual target set via the status payload for retry-failed and per-scene runs.

### REST/SSE: no merge guard needed

The old REST-clobbers-SSE bug went away as a side effect of Section 1: with `is_stale` now AND'd with `not is_running_task`, REST `/status` returns `stale: false` for every healthy run, matching SSE. The existing `items_done` regression guard in `useProjectStatus` stays as-is. The `in_flight` array on `StageInfo` is consumed by `drawProgress.hydrate()` only — the Zustand store is the source of truth for live data after mount, so REST `in_flight` overwriting an SSE-driven Zustand state is structurally impossible.

---

## Section 3 — Frontend: UI Layout

The right rail (`web/src/pages/rooms/DrawRoom.tsx`) becomes the live cockpit. Width grows from 280px → 320px. The donut stays at the top. The credits-estimate and generation-options cards are removed from the room.

### Right rail composition by state

**At rest** (no draw running):
```
PANEL PROGRESS
  [donut] 47/120
  ● Generated 47
  ● Pending   72
  ● Failed     1

▾ BY SCENE (collapsed by default)

[GENERATE ALL PENDING (72)]
[RETRY FAILED (1)]
```

**Running**:
```
PANEL PROGRESS
  [donut] 47/120
  ● Generated 47
  ● Pending   72
  ● Failed     1

  [████████░░░░░░] 39%
  ETA 18m · 4.2 / min

IN FLIGHT (4)
  ● scene_3 / 08    14s
  ● scene_3 / 09     8s
  ● scene_4 / 01    11s
  ● scene_4 / 02     3s

RECENT FINISHES
  ✓ scene_3 / 06    12s
  ✓ scene_3 / 05    18s
  ✗ scene_2 / 11   failed
  ✓ scene_2 / 10     9s
  ✓ scene_2 / 09    14s

▾ BY SCENE (auto-expands when any scene has a failure)
  scene_1 ████████ 12/12
  scene_2 ████████ 10/11
  scene_3 ███░░░░░  7/12
  scene_4 █░░░░░░░  2/12
```
Action buttons hidden while running.

**Stale** (RUNNING in state.json but no live task — server restart):
```
⚠ Last progress 6m ago — server may have stopped.
  [Reset stage]

PANEL PROGRESS
  ...
```
Stale strip sits inside the PANEL PROGRESS card, above the donut. `Reset stage` calls existing `useResetStale`.

### Per-panel cards (`PanelCard.tsx`)

| State | Visual |
|-------|--------|
| `pending` | Light gray bg, "NOT YET GENERATED" — unchanged |
| `queued` (NEW) | Light gray bg + dotted gold border + small `QUEUED` pill — subtle, distinct from generating |
| `generating` | Black bg, gold pulsing "GENERATING…" — unchanged in look, now driven by precise `inFlight` set |
| `generated` / `regenerated` / `accepted` / `failed` | Unchanged |
| `stale` | Removed |

`STATE_BADGE.stale` is deleted. The "GENERATION STALE" full-card treatment is deleted.

### Flash on finish

When a `panel_done` event arrives and the matching card is mounted in the grid, apply a 600ms `outline` animation (gold for ok, red for failed). Implemented as a one-shot keyed by `${sceneId}-${panelNumber}-${doneAt}`. Ties the RECENT ticker to the gallery without requiring the user to scroll.

### Removed cards

- `DrawCreditsEstimate` — content already shown in `ConfirmDrawer` via `costForConfirm`.
- `GenerationOptionsPanel` (quality preset) — moved into `ConfirmDrawer` body so the user picks at the moment they kick off the run. Also still reachable from the project settings page.

`ConfirmDrawer` (web/src/components/ui/ConfirmDrawer.tsx) gains an optional `extraBody?: ReactNode` slot so DrawRoom can inject the quality-preset selector. Existing callers (regen flows, etc.) ignore the slot.

---

## Section 4 — Out of Scope

- A `[Cancel run]` button. Stage cancellation isn't wired today; adding it is a separate design.
- Replacing `useResetStale` with a stage-scoped variant. The current global behavior is fine for v1 — the banner only appears for one stage at a time in practice.
- Exposing the precise per-run target set (for retry-failed / per-scene runs) in the status payload. v1 approximates "queued" as "pending while running."
- Background polling (`refetchIntervalInBackground: true`). The new SSE-driven UI is enough; users returning to a tab get a fresh poll on focus.
- Restoring credits estimate / quality preset to a docked location. They live in ConfirmDrawer + project settings.

---

## Migration & Compatibility

- `StageState.last_progress_at` is a new optional field. Existing `state.json` files without it deserialize fine (Pydantic default = None). `is_stale` falls back to `started_at` when `last_progress_at` is None — preserves current behavior for in-flight projects on first load after upgrade.
- `StageInfo.in_flight` and `StageInfo.last_progress_at` in the API: frontend tolerates missing fields (undefined → empty array / null).
- Per AGENTS.md: breaking JSON/model changes are acceptable; no shims required.
- `panel_start` / `panel_done` events: clients that don't recognize them ignore (the SSE handler in `pipeline.ts` already has a `try { } catch {}` for malformed events; new types simply aren't dispatched).

---

## Testing

Backend (`novel_to_comic/tests/`):
- `test_state.py` — extend `TestIsStale` for the new heartbeat-based logic; add `test_heartbeat_resets_stale_window`, `test_no_heartbeat_falls_back_to_started_at`.
- New `test_stage_runtime_panel_events.py` — covers `emit_panel_start` / `emit_panel_done`.
- `test_draw_in_flight.py` — verify `_generate_panel` adds/removes from `app.state.draw_in_flight` (use a fake semaphore).
- `test_status_payload.py` — `_stage_payload` returns `stale=False` while live task is running and stale-by-clock; `stale=True` when no task.

Frontend (`web/src/__tests__/`):
- Update `panelState.test.ts` for new state machine; add `queued` cases; remove `stale` cases.
- New `drawProgress.test.ts` — hydrate from status, apply panel_start/done, clear; throughput sliding-window math.
- New `pipelineStatusEventsRest.test.ts` — REST/SSE merge guard (cached `stale: false` not clobbered by REST `stale: true` when last_progress_at is fresh).
- Existing `pipelineStatusEvents.test.ts` — extend for stale-handling on stage_progress.

Manual verification (no automated browser test required for v1):
- Start a draw run on a project with ≥ 30 panels. Watch IN FLIGHT churn, RECENT populate, ETA / throughput stabilize after 3 finishes.
- Switch tabs for 6+ minutes; return — panels should still show pending/queued/generating, never STALE. Live cockpit reflects current state from on-focus refetch.
- Kill the server mid-run, restart. Re-open the project. Stale banner appears with `Reset stage`. Click → state resets to pending.
- Fail a panel mid-run (provider error). RECENT shows the failure; BY SCENE auto-expands.

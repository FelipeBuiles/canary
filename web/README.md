# Canary Web UI

React + TypeScript + Vite frontend for Canary. This is the default interface
for controlling the pipeline, reviewing artifacts, and exporting comics.

## Running

```bash
# Development (from /web)
npm install
npm run dev     # Vite dev server at http://localhost:5173

# Or via the CLI (starts both backend and serves this frontend)
cd ..
pipeline serve --projects-dir . --dev
```

## Building

```bash
npm run build   # outputs to dist/
```

## Architecture

- `src/App.tsx` — main router and app shell
- `src/pages/` — page components (Library, Settings, PrimitiveReference, etc.)
- `src/components/` — shared UI components
- `src/layout/` — Shell, SideNav, TopNav, ProjectRooms

The web UI communicates with the FastAPI backend via REST + SSE. See
`docs/reference/api-routes.md` for the full API reference.

## Stations (UI grouping)

The UI presents the 9 backend pipeline stages as 4 user-facing **stations**:
`01 Story → 02 Look → 03 Panels → 04 Book`. The intermediate stages (`adapt`,
`plan`, `storyboard`, `direct`) auto-run after cast approval and appear as
read-only inspect drawers with an `auto · view` badge — a placeholder is shown
if their content isn't generated yet. Panel review is flag-by-exception:
generated panels are accepted by default and users flag the ones needing
re-work. This grouping is presentation-only; backend stages remain discrete
and ordered. See `docs/proposals/four-station-redesign.md` for the full plan.

Key pieces:

- `src/lib/stations.ts` — station ↔ stage mapping, state derivation, the
  `BACKEND_STAGE_TO_STATION_ROUTE` landing map
- `src/components/composites/ApprovalBar.tsx` — the one standing approval bar
  (every gated room ends with it; the sidebar has no CTA)
- `src/components/InspectDrawer.tsx` — script / shot-plan / prompts drawers
- `src/lib/panelState.ts` — flag-by-exception display states
- The old `adapt` / `shot-plan` / `direct` rooms are gated behind Dev Content
  (`src/lib/devContent.ts`, **defaults OFF**) — their routes redirect to the
  pipeline position otherwise.

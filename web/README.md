# Scenewright Web UI

React + TypeScript + Vite frontend for Scenewright. This is the default interface
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

## Tests and native prerequisites

```bash
npm ci
npm test
npm run lint
```

The jsdom environment uses the real `canvas` 2D implementation, with media-query
and resize-observer implementations in `src/test/setup.ts`. Canvas drawing is
not replaced by a no-op stub.

On platforms without a prebuilt canvas binary, including Linux ARM64, installation
requires Python 3, a C++ compiler, `make`, `pkg-config`, and Cairo/Pango development
libraries. For Debian/Ubuntu:

```bash
sudo apt-get install python3 make g++ pkg-config libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev
```

The root Dockerfile installs these in its frontend build stage, not the final
runtime image. Canvas currently depends on the upstream-deprecated
`prebuild-install` installer; npm may report that separate install-time notice.

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
and ordered. `src/lib/stations.ts` is the implemented mapping.

The replacement complete-page architecture is recorded in ADRs 0003-0015
(`docs/adr/`).

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

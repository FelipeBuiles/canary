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

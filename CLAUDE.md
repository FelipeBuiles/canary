# Claude Code Compatibility

Read `AGENTS.md` first. It is the canonical instruction file for this repo and
is intentionally kept compact for all coding-agent harnesses.

Open `docs/reference/agent-context.md` only when you need detailed Canary
pipeline, model, stage, assembly, or artifact context. Documentation policy is
in `docs/README.md`.

**Important:** The CLI only has `init` and `serve` commands. All pipeline
operations (run, approve, status, export) go through the FastAPI web server.
See `server/routers/pipeline.py` for the API endpoints.

Do not work in a separate git worktree — this is a single dev project and it
would be simpler to keep everything in main branch for now.

## Agent skills

### Issue tracker

Issues and PRDs live in GitHub Issues for `FelipeBuiles/canary`, using the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Use the default canonical labels: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, and `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

This is a single-context repo; read root `CONTEXT.md` and relevant ADRs in `docs/adr/`. See `docs/agents/domain.md`.

## Commands

```bash
# Start and health-check the development stack (recommended)
./scripts/dev.sh

# Start the zero-cost fixture replay stack
./scripts/dev.sh --mock

# Check services without starting them
./scripts/dev.sh --check

# Start the pipeline web server
cd novel_to_comic && pipeline serve --projects-dir ../projects

# Start the frontend (Vite dev server)
cd web && npm run dev

# Run Python tests
cd novel_to_comic && uv run pytest tests/

# Lint Python
cd novel_to_comic && uv run ruff check src/

# Run frontend tests
cd web && npm test
```

## Environment

The launcher manages or checks the local LiteLLM and mock-model services. For
manual serving, configure the project and gateway environment as described in
`novel_to_comic/README.md` and `docs/reference/mock-model-replay.md`.

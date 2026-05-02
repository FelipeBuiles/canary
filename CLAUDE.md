# Claude Code Compatibility

Read `AGENTS.md` first. It is the canonical instruction file for this repo and
is intentionally kept compact for all coding-agent harnesses.

Open `docs/reference/agent-context.md` only when you need detailed Canary
pipeline, model, stage, assembly, or artifact context.

**Important:** The CLI only has `init` and `serve` commands. All pipeline
operations (run, approve, status, export) go through the FastAPI web server.
See `server/routers/pipeline.py` for the API endpoints.

Do not work in a separate git worktree — this is a single dev project and it
would be simpler to keep everything in main branch for now.

## Commands

```bash
# Start full infra (LiteLLM gateway + Langfuse) — required before serving
docker compose up -d

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

Copy a project's `config.yaml` for API keys. LiteLLM gateway must be running
(`docker compose up litellm`) before the pipeline server can generate anything.
Key env vars: `LITELLM_BASE_URL`, `LITELLM_API_KEY`, `LITELLM_MASTER_KEY`.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- For cross-module "how does X relate to Y" questions, prefer `graphify query "<question>"`, `graphify path "<A>" "<B>"`, or `graphify explain "<concept>"` over grep — these traverse the graph's EXTRACTED + INFERRED edges instead of scanning files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)

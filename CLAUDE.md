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

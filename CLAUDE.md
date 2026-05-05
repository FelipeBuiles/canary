# Delegation Rules — MANDATORY

**STOP before every Read. Run `ask-ai` or `ai-write` instead unless the task requires editing/debugging.**

| If you are about to... | You MUST... |
|------------------------|-------------|
| Read 1+ file >300 lines to answer a factual question | `ask-ai` — do NOT use Read |
| Read 2+ files to summarize or understand something | `ask-ai` — do NOT use Read |
| Grep across 5+ files for a bulk answer | `ask-ai` — do NOT use Bash grep |
| Write boilerplate, test stubs, fixture files, or docs | `ai-write` — do NOT write it yourself |
| Edit, debug, or reason across abstractions | Use Claude directly (Read is fine) |

```bash
# Tools are in PATH via ~/Code/delegate
ask-ai "what does X do?" src/foo.py src/bar.py
ai-write "pytest stubs for all public functions" --ref src/utils.py --out tests/test_utils.py --type test
```

**Never delegate:** editing code, debugging logic, security review, cross-abstraction reasoning.

---

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

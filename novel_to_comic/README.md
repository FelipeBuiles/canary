# Novel-to-Comic Engine

See the main pipeline documentation at `docs/novel-to-comic-pipeline.md`.

## Quick Start

From the repository root, the development launcher starts and health-checks
the backend, Vite client, LiteLLM, and LiteLLM's Docker-managed Postgres:

```bash
./scripts/dev.sh                 # live models
./scripts/dev.sh --mock          # zero-cost fixture replay
./scripts/dev.sh --check         # report status without starting services
./scripts/dev.sh --observability # also start/check the optional Langfuse stack
```

It reuses healthy services that are already running. Processes started by the
launcher stop on Ctrl-C; Docker dependencies remain running for the next
session. Run `./scripts/dev.sh --help` for fixture and Docker controls.

### Manual setup

```bash
cd novel_to_comic
pip install -e .
playwright install chromium

# Initialise a project
cd my-project-dir
pipeline init ../path/to/novel.epub

# Start the web server (pipeline operations go through the API, not CLI)
pipeline serve --projects-dir .
```

## Architecture

The pipeline engine (`src/novel_to_comic/`) is a Python package that exposes a
FastAPI web server. All pipeline operations (run, approve, export) are HTTP API
endpoints — there is no `pipeline run` command.

For documentation on the 9-stage pipeline, model configuration, and project
structure, see `docs/novel-to-comic-pipeline.md`.

For agent-facing developer documentation, see `AGENTS.md` and
`docs/reference/agent-context.md`.

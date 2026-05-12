# Novel-to-Comic Engine

See the main pipeline documentation at `docs/novel-to-comic-pipeline.md`.

## Quick Start

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

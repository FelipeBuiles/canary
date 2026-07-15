# Mock model replay

Canary includes a hidden, local-only replay mode for UI tests and demos. It
keeps the real nine-stage pipeline, API calls, progress events, checkpoints,
artifact writes, panel review, and compose/export flow, while replacing paid
text and image providers with an OpenAI-compatible fixture service.

The current recommended fixture is the local **The Call of Cthulhu** project.
Text callbacks replay its Story Bible, style directions, screenplays, and
layout decisions. Image callbacks first match the exact recorded prompt; when
a new prompt has no exact match, the service selects a deterministic Cthulhu
image and crops it to the requested generation dimensions.

## Start the development stack

The root launcher starts the mock replay service, backend, and Vite client,
then waits for each health check:

```bash
./scripts/dev.sh --mock
```

The default fixture is the local **The Call of Cthulhu** project described
below. Override it with `--fixture /path/to/completed-project`. The launcher
sets the server-level operator gate automatically, but the project being run
must still contain `mock_mode: true` in its `config.yaml`.

Use `./scripts/dev.sh --check --mock` to report health without starting
anything. Mock mode does not start LiteLLM or its Docker database because all
model traffic goes to the replay service.

## Start the replay service manually

From `novel_to_comic/`:

```bash
uv run canary-mock-models \
  --source ../projects/63f06b92-a5c6-4f5b-b0e5-c330abe49982/the-call-of-cthulhu
```

It listens on `127.0.0.1:4010` by default. Its health endpoint is
`http://127.0.0.1:4010/health/liveliness`.

## Enable a demo project

Add this field to that project's `config.yaml`:

```yaml
mock_mode: true
```

Then start the Canary server with the operator gate enabled:

```bash
CANARY_MOCK_GENERATIONS_ENABLED=true uv run pipeline serve
```

The project flag is deliberately absent from the config API and UI. Both the
project flag and operator environment gate are required. If `mock_mode: true`
is present without the environment gate, model calls fail closed instead of
falling back to paid providers.

To run the replay service on another port, pass `--port` and set
`CANARY_MOCK_MODEL_BASE_URL` on the Canary server to the matching URL.

## Billing behavior

When the two-part gate is active:

- stage, style, cover, cast, and panel-regeneration estimates are zero;
- no credit reservation is placed;
- replay responses are tagged with `cost_source: mock`;
- mock usage never creates a settled credit debit, including paths that
  normally apply the one-credit minimum.

The replay server should only be bound to localhost or an internal test
network. It has no authentication because it never calls a provider and is
intended as a developer process, not a production endpoint.

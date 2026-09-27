# Dependency maintenance

**Status: Current.** Manifest and compatibility review: September 18, 2026.
Versions below describe the checked-in dependency refresh, not a production
rollout. The manifests, lockfiles, Dockerfiles and CI remain authoritative.

## Dependency boundaries

| Environment | Authority | Installation |
| --- | --- | --- |
| Python application | `novel_to_comic/pyproject.toml`, `novel_to_comic/uv.lock` | `uv sync --project novel_to_comic --locked --extra web --extra dev` for development/CI |
| LiteLLM gateway | `litellm/pyproject.toml`, `litellm/uv.lock` | Independent environment; both Dockerfiles install this same lock |
| Browser application | `web/package.json`, `web/package-lock.json` | `npm ci` in `web` |
| Browser automation tooling | Root `package.json`, `package-lock.json` | `npm ci` at repository root |
| Observability | Python `web` extra and browser lockfile | PostHog SDKs and HTTP OTLP exporters; no local analytics services |
| Runtime and release tools | `.nvmrc`, Dockerfiles, `.github/workflows/ci.yml` | Node 24.21.0, Python 3.12, uv 0.12.17, Fly CLI 0.4.104 |

Do not install the gateway into the application's virtual environment. Its
Rich and protobuf constraints differ from the application dependencies. The
production gateway uses `/app/.venv-litellm`; the standalone gateway image uses
`/app/.venv`. Neither is resolved from an upstream gateway image plus a second,
unlocked package installation anymore.

The database-enabled gateway explicitly locks Prisma 0.15.0 and psycopg 3.3.6.
LiteLLM's PyPI `proxy` extra does not include its entire Docker database runtime;
see the upstream [dependency groups](https://github.com/BerriAI/litellm/blob/v1.101.0/pyproject.toml)
and [image build](https://github.com/BerriAI/litellm/blob/v1.101.0/Dockerfile).
Both Canary images generate Prisma's client and cache its matching CLI/engines
at build time. They retain the reviewed Node runtime, but remove npm after
client generation. The production supervisor adds the gateway's executable
path only to the gateway process, not the application's Python environment.

`scripts/smoke_gateway.py` verifies both database-free startup and a fresh
PostgreSQL-backed startup, including API-key creation and a mock request using
that generated key. It creates uniquely named disposable containers/network
and never uses the operator's existing Compose database or provider credentials.
Normal CI runs this after building the gateway image. Installing successfully
or serving a database-free health check alone would miss this failure mode.

## September refresh

The app lock updates 53 existing Python package versions, including transitive
packages. The root and web npm lockfiles are resolved against the reviewed
manifests. The showcase video project remains local-only and is outside CI.

| Component | Previous resolved version or runtime | Selected version |
| --- | --- | --- |
| LiteLLM | 1.83.14 | 1.101.0 |
| Google Gen AI SDK | 1.75.0 | 2.24.0 |
| Vertex AI SDK | Separately installed, unpinned | 2.1.3, shared gateway lock |
| Google Auth | Separately installed, unpinned | 2.58.0, shared gateway lock |
| FastAPI | 0.135.3 | 0.141.1 |
| Pydantic | 2.13.1 | 2.13.5 |
| Stripe Python | 15.1.0 | 15.6.1 |
| Pillow | 12.2.0 | 12.3.0 |
| Python Playwright | 1.58.0 | 1.63.0, matching Chromium installed by Playwright |
| React / React DOM | 19.2.x | 19.3.0 |
| React Router | 7.18.2 | 7.18.4 |
| Vite / Vitest | 8.0.x / 4.1.x | 8.3.0 / 5.0.1 |
| ESLint | 9.x | 10.11.0 |
| Remotion packages | 4.0.524 | 4.0.526, exact matched versions |
| CI / image Node | 20 / 22 | One Node 24 LTS runtime |
| PostgreSQL / Redis / ClickHouse | Floating 17 / floating 7.4 / 26.3.9.8 | 17.11 / 7.4.11 / 26.3.33.24 |

Supabase, TanStack Query, Tailwind, Lucide, Zustand, testing libraries, AWS SDK
packages, OpenTelemetry, Ruff, pytest, root Playwright tooling and related types
are also refreshed. An unchanged package can already be current; the lockfiles,
not this selected-highlights table, contain the complete inventory.

## Compatibility decisions

### Keep TypeScript on the supported 6.0 line

The reviewed registry publishes TypeScript 7, but `typescript-eslint` 8.70.0
supports TypeScript below 6.1. Both TS projects use `~6.0.3`. Do not use
`--force` or `--legacy-peer-deps` to conceal an unsupported compiler/parser pair.

Remotion 4.0.526's ESLint configuration still pins an older TypeScript ESLint
adapter. The video manifest explicitly overrides that nested dependency with
its direct, reviewed 8.70.0 adapter. All Remotion packages themselves remain in
exact lockstep. Revisit the override when Remotion updates its dependency.

### PostHog replaces the local analytics stack

The Python web extra includes PostHog and HTTP OpenTelemetry exporters. Browser
errors use PostHog with build-time source-map upload. Langfuse, its storage
services, and Sentry are retired; there is no Langfuse version migration to run.
Keep any historical volumes until their data is no longer needed. See the
[operating guide](observability.md) for activation and data boundaries.

### Keep stateful service majors and the Codex runtime deliberate

PostgreSQL stays on 17 for the queue and LiteLLM databases. Major upgrades
require data-format, restore, and resource tests.

The optional `openai-codex` SDK and bundled runtime are pinned to 0.156.1.
That adapter has an explicitly restricted execution, authentication, tool and
funding contract; its pinned
runtime is also part of the recorded generation identity. Runtime upgrades
need a capability/security review and opt-in local-auth test. See the
[Codex capability reference](codex-dev-capabilities.md). No paid-provider
fallback, model alias, image retry policy or existing edition selector changes
as part of this dependency refresh.

## Upgrade-sensitive contracts

`litellm/tests/test_gateway_contracts.py` imports the actual installed gateway
and Google SDK rather than relying on the lightweight fallback stubs used by
some application tests. It covers multipart and buffered HTTP failures,
Anthropic refusal metadata in streaming and non-streaming responses, Google
image controls, input images, usage/cost mapping and retry classification.

Both gateway patch scripts fail the build when their upstream anchors or
installed targets are missing. The HTTP patch preserves provider status/body
without consuming or copying a submitted image into the sanitized exception.
The refusal patch preserves metadata only; it does not change request policy.
Reapplying a recognized patch is harmless. Unknown layouts require review.

Sentry tests preserve disabled-by-default tracing/replay, masked replay media,
bounded sample rates, sensitive-header redaction and identity clearing. They do
not send telemetry. The frontend audit now delegates to npm without the old
React Router advisory exception or a custom JSON parser that could hide errors.

FastAPI route assertions use the public OpenAPI paths rather than assuming all
entries in `app.routes` are eager routes. Full request/response tests remain in
place. Telemetry tests distinguish bounded log prompts from the complete frozen
prompt actually sent to the image provider.

Ruff's historical `E4`, `E7`, `E9`, `F` gate is explicit. Upgrading Ruff does not
silently opt this repository into its expanded defaults or mass-rewrite unrelated
code. React lint findings were fixed by separating render-time geometry from
pointer handlers and moving connection-state transitions to user actions.

## Validation and maintenance

Normal PR CI installs the checked-in locks, checks peer/dependency consistency,
runs backend and browser tests, lints and compiles the frontend, builds the
production Docker image, and tests/builds the real gateway. Python production environments are exported without the editable
project and audited with `pip-audit`; npm audits cover application and tooling.
An audit failure is not waived automatically.

For a deliberate update, first inspect upstream release notes and peer ranges,
then update the manifests and regenerate locks:

```sh
uv lock --project novel_to_comic --upgrade
uv lock --project litellm --upgrade
npm update --package-lock-only
(cd web && npm update --package-lock-only)
```

These commands stay within manifest constraints; major upgrades require an
explicit manifest decision. Use `npm ci`, not a fresh unlocked install, for
validation. Run `python3 scripts/check_docs_reliability.py` after reference edits.
Rebuild both Dockerfiles after gateway changes and install Chromium through the
upgraded Python Playwright package.

Before applying Compose changes to persistent installations, record current
image versions and take verified backups of PostgreSQL, ClickHouse and object
storage. Rehearse against restored copies. Retain both database and application
rollback paths; an old image may not understand a newly migrated schema. Never
use `docker compose down -v` against persistent user data as an upgrade step.

CI and disposable integration smoke tests do not prove live provider output
quality, account authentication, Stripe payments, Sentry delivery or a production
migration. Those remain credentialed, controlled rollout checks. Deployment
still requires a human-triggered main-branch workflow, all validation jobs, the
existing drain/idle barrier and post-deployment version verification.

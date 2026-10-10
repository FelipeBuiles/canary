# Pre-push and release checks

Status: Current. Run the complete local gate from the repository root:

```sh
./scripts/check_all.sh
```

The script also works from another directory using its absolute path. It selects
the Node version in `.nvmrc` from an existing nvm installation when needed, supplies
non-secret Supabase CI placeholders, and disables source-map uploads for this
process. It runs the full provider-free backend, frontend, and gateway unit
suites, dependency compatibility/audits, docs reliability, Ruff, frontend lint,
and the production frontend build. The web component builds before running
Vitest, so production hydration and session-restore tests execute on a fresh
checkout. It also runs the backend public-page and SPA mount contracts against
that build. A failed check exits nonzero and stops the
gate. It does not start development servers, build Docker images, or run the
separate real PostgreSQL contracts.

Every command shows a numbered RUN and PASS/FAIL line with elapsed time. Terminals
show a live spinner; redirected output and Git GUI clients receive a heartbeat
every ten seconds while a check runs. Successful command output stays in a
per-run temporary `canary-checks-*` directory, printed at the start and finish.
It contains numbered command logs and `summary.log` with each result and duration;
logs remain available until the system cleans its temporary directory. A failure
prints its diagnostics immediately and stops the gate. Use
`./scripts/check_all.sh --verbose` to stream all command output too, including
passing frontend test console diagnostics. The same flag is supported by
`scripts/check_release.py` components.

The Bedrock transport tests narrowly filter Pydantic's runtime-immutability
warnings for two LiteLLM 1.101.0 TypedDict fields (`summary` and
`langfuse_environment`). Those contracts do not rely on dict immutability.
Other warnings remain enabled; revisit the filters when upgrading LiteLLM.

These root package commands are also available:

```sh
npm run check:push
npm run check:release
```

`check:push` invokes the complete local gate above. Expect several minutes;
browser-heavy backend tests and initial package/audit downloads dominate runtime.

The full backend suite runs in up to four isolated pytest workers. Set
`CANARY_BACKEND_WORKERS=0` for serial debugging, or another worker count to limit
local resource use. For backend lint and tests alone, run
`python3 scripts/check_release.py backend`. Focused pytest commands remain serial;
see [backend test maintenance](../reference/backend-tests.md) for profiling.

Frontend tests use compact progress and show console output for failed tests.
The `ui` project uses isolated VM workers to reuse jsdom initialization; real
PostHog SDK reload tests run separately in the `sdk-reloads` project with fresh
processes. For verbose debugging from `web/`, run:

```sh
npm test -- --reporter=verbose --silent=false
```

For a focused check, `python3 scripts/check_release.py fast` retains the earlier
bounded gate. It audits both locked production
Python dependency sets with the same pinned pip-audit command used by CI; checks
installed Python package compatibility; runs docs reliability and backend Ruff;
runs all publication, auth, security-boundary, lifecycle, observability, job,
queue and pipeline-failure regressions; audits frontend
and root dependencies; runs focused metadata/replay, OAuth/auth-form and artwork/viewing tests, frontend lint and
production build. It does not claim the full backend, gateway, Docker or real
PostgreSQL suites passed.

Backend checks run from `novel_to_comic/`, as CI does, and hide the actual ignored
`web/dist` from application route registration through a test-process-only path
probe. Fixture builds remain visible. No build files are moved or deleted. This
catches both working-directory dependencies and tests accidentally satisfied by
a previous frontend build. CI uses that same runner for backend/security tests,
and uses the same dependency-audit and disposable-database components as the local command.
The web CI job runs `python3 scripts/check_release.py web-contracts` after its
build to cover the real HTML and application mounts separately. That component
rejects a missing or incomplete build before invoking pytest; it does not use
the source-only runner.

`check:release` runs the full local test/build coverage plus gateway PostgreSQL-backed
startup smoke checks, the production Docker build, and real database authorization,
ledger, purchase-outbox and auth-signup-outbox tests. Expect several minutes and substantial Docker
CPU/network use. It requires an **explicitly disposable**, fresh PostgreSQL
database named `canary_test` on loopback, `CREDIT_TEST_DATABASE_URL`, and
`CANARY_DISPOSABLE_DATABASE=1`. It bootstraps that database with the existing CI
fixtures/schema; never point it at an application database. It does not reset or
delete databases. Stop your test database afterward. Browser binaries must already
be installed. No checks are silently skipped: missing tools, unavailable audits,
missing disposable database configuration and nonzero checks fail the command.

Prerequisites: repo-supported Node/npm, uv, synchronized app/gateway virtualenvs
(`uv sync --project novel_to_comic --locked --extra web --extra dev` and
`uv sync --project litellm --locked`), installed Chromium, and installed npm
packages. Full release also needs Docker and psql in PATH. Individual components
are available via `python3 scripts/check_release.py --help`, so CI jobs can retain
their existing provisioning and parallelism.

The tracked [pre-push hook](../../.githooks/pre-push) invokes
[check_all.sh](../../scripts/check_all.sh) and blocks the push on any failed
check. Activate it once per checkout:

```sh
git config --local core.hooksPath .githooks
```

Git does not activate tracked hooks automatically on clone. If a checkout already
has hooks, preserve those checks and invoke `scripts/check_all.sh` from its existing
pre-push hook instead of replacing its hook configuration. Hook activation does
not push or deploy.

Earlier validation: the fast path passed 67 backend regressions and 33 focused frontend
tests, audits, docs, Ruff, lint and build. Temporary files containing the earlier
vulnerable lock were rejected for CVE-2026-101918; the earlier build-dependent
crawler test failed while the ignored local build remained intact. Missing uv
and missing disposable database configuration both returned nonzero. These
negative checks did not downgrade installed dependencies, switch the checkout,
change production or transmit manuscript data.

The shared database component additionally passed all 30 authorization, ledger
and purchase-outbox tests on a fresh existing-image PostgreSQL container, which
was stopped and removed afterward.

The complete local gate components also passed: 2,745 backend tests (9 skipped),
61 page-contract tests, 798 frontend tests, 36 gateway tests, both gateway startup
smokes and both Docker builds. When a tool interruption stopped the original
runner during frontend tests, the completed components were retained and the
remaining components resumed; the abandoned test database was removed.

Tracking follow-up: the expanded fast path passed 168 backend regressions
(1 skipped) and 122 frontend cases, audits/docs/Ruff/lint/build. Full release
passed 32 real database checks (including the new local signup trigger),
2,758 backend tests (9 skipped), 61 contracts, 804 frontend cases, 36 gateway
cases, both gateway startup modes and production Docker build. Subsequent
focused final stage checks passed 91 cases; real Chromium continuity/artwork
fixtures passed seven checks with external traffic blocked. No live signup,
purchase or paid generation was used.

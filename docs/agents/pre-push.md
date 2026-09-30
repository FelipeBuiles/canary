# Pre-push and release checks

Status: Current. These checks do not push, deploy, migrate production or activate
Git hooks. Run them from any directory using the script’s absolute path, or use
these root package commands:

```sh
npm run check:push
npm run check:release
```

`check:push` is the bounded default (about one minute on the development Mac,
excluding initial package/audit downloads). It audits both locked production
Python dependency sets with the same pinned pip-audit command used by CI; checks
installed Python package compatibility; runs docs reliability and backend Ruff;
runs all publication, auth and security-boundary regressions; audits frontend
and root dependencies; runs focused metadata/replay tests, frontend lint and
production build. It does not claim the full backend, gateway, Docker or real
PostgreSQL suites passed.

Backend checks run from `novel_to_comic/`, as CI does, and hide the actual ignored
`web/dist` from application route registration through a test-process-only path
probe. Fixture builds remain visible. No build files are moved or deleted. This
catches both working-directory dependencies and tests accidentally satisfied by
a previous frontend build. CI uses that same runner for backend/security tests,
and uses the same dependency-audit and disposable-database components as the local command.

`check:release` adds the full backend and page-contract suites, all frontend
checks, root checks, gateway dependency/provider tests and PostgreSQL-backed
startup smoke checks, the production Docker build, and real database authorization,
ledger and purchase-outbox tests. Expect several minutes and substantial Docker
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

No existing Git hooks or `core.hooksPath` were changed. To opt in, invoke
`python3 scripts/check_release.py fast` from your existing pre-push hook, preserving
its existing checks, or create a hook if none exists. The command is also suitable
for a release checklist without installing a hook.

Validation: the fast path passed 67 backend regressions and 33 focused frontend
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

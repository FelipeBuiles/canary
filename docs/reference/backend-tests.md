# Backend test maintenance

**Current.** The full provider-free backend suite remains the normal CI gate.
PostgreSQL transaction and authorization checks run separately against an
explicitly disposable database. Test count alone is not a quality or speed goal.

## Measure before changing coverage

From the repository root, capture a full run with filenames and fixture timings:

```sh
novel_to_comic/.venv/bin/python scripts/run_backend_checks.py tests -q \
  --durations=20 -o junit_family=xunit1 --junitxml=/tmp/canary-backend.xml
python3 scripts/audit_backend_tests.py --junit /tmp/canary-backend.xml \
  --json /tmp/canary-backend-audit.json
```

The runner hides an ignored local frontend build, matching CI's source-only
checkout. The audit uses only the standard library; it imports no application
code, runs no tests, and makes no provider calls. It reports expensive modules,
test functions including their setup/teardown, large case expansions, overlapping
JUnit identities, and exact AST duplicate candidates. The JSON retains all rows;
`--limit` changes only the console display.

To inspect the complete CI workload, pass all four shard reports in one call:

```sh
python3 scripts/audit_backend_tests.py --junit \
  /tmp/shard-0.xml /tmp/shard-1.xml /tmp/shard-2.xml /tmp/shard-3.xml
```

Do not compare summed shard time with parallel wall time. Keep machine, test
selection, browser mode, database availability, and other running work comparable.
Failed or interrupted runs can locate problems but are not clean speed baselines.

## Decide what can be removed

- Identify the current behavior or regression each candidate protects. A test
  is outdated when its contract is obsolete, not merely because its date or name
  mentions an old implementation. Retained editions and refusal, billing,
  authorization, cancellation and ambiguity guards still need coverage.
- For duplicates, compare fixtures, imports, inputs and asserted outcomes. Name
  the retained test in the change description. Identical executed lines alone do
  not prove equivalent assertions, and identical bodies can use different helpers.
- For parameter matrices, retain each distinct branch and relevant interaction.
  Apply model/provider variants to selection, payload, capability and tariff
  contracts; generic transport failures need not multiply across every alias.
- Put cheap value tables at the unit boundary. Keep focused integration tests
  for wiring and state transitions instead of rebuilding the app or browser for
  every value. Keep concurrency tests event-driven where possible.
- Inspect orchestration too: running a suite and then a subset repeats coverage.
  The release backend check runs full-page contracts in the full suite once;
  CI's database job runs real PostgreSQL contracts while the backend shards own
  the provider-free billing/security regressions.

For each removal or simplification, explain the retained evidence and run the
affected tests. Broaden to the full suite for shared fixtures or orchestration.
Re-measure after the change. The audit never automatically deletes or skips tests.

## Keep expensive dependencies real without repeated startup

The session fixture in `novel_to_comic/tests/conftest.py` reuses up to two Chromium
processes on their owning threads. Every lettering operation receives a fresh
browser context and page, closed even on failure. The production renderer still
executes its actual engine, fonts, validation and screenshots; results are not
mocked or cached by this fixture. Production browser lifetime is unchanged.
Fixture tests check cleanup, thread ownership, and real DOM/cookie isolation.
The real isolation test waits for cold startup separately from its 15-second
operation checks. On failure, captured lifecycle logs identify the worker and
browser phase; a timed-out operation also dumps thread stacks.

Use `--fresh-lettering-browser` on the same pytest command to reproduce production's
browser startup per operation or to compare the cost of reuse. A missing or blocked
Chromium remains a failure; the fixture does not skip browser coverage.

The image-preview retry test advances admission's clock along with its fake
retry pacer. Admission's own tests cover cooldown enforcement. Supervisor tests
keep real fake-child processes, signals, durable recovery writes and crash
budgets, with short test-local sleep intervals and deterministic health probes.
Recovery transition tests independently assert the exact backoff and health
windows without wall-clock waits.

The operations snapshot test fixes external disk measurements while exercising
the storage alert. Its repeated reads can then verify journal and credit evidence
stays unchanged even when other processes write to the host filesystem.

## Run the local suite in isolated workers

The complete local gate and its backend component use
[pytest-xdist](https://pytest-xdist.readthedocs.io/en/stable/distribution.html)
with up to four worker processes (bounded by the local CPU count) and the
`worksteal` scheduler. Each process owns its Python state, temporary directories,
and lazily reused Chromium processes. The same provider-free cases run; no
rendering results are cached or coverage removed. The source-only frontend probe
is configured in every worker before collection and still permits fixture builds.

Run just backend lint and the full parallel suite from the repository root:

```sh
python3 scripts/check_release.py backend
```

Set `CANARY_BACKEND_WORKERS` to choose the worker count. Use `0` for serial
debugging or comparable JUnit profiling:

```sh
CANARY_BACKEND_WORKERS=0 python3 scripts/check_release.py backend
```

Focused pytest commands and the JUnit command above remain serial unless `-n`
is explicitly supplied. Depot already distributes filenames across four
two-CPU shards; those shards and the real PostgreSQL job retain their existing
execution model. Parallelism is enabled by the local full-suite component,
without a global pytest `addopts` setting.

## Local observations (2026-10-07)

| Check | Original startup/waits | Optimized |
| --- | ---: | ---: |
| Full serial backend suite | 291.09 s | 180.40 s |
| Supervisor tests, 12 cases | 37.61 s | 4.63 s |
| Image preview tests, 17 cases | 14.55 s | 0.80 s |
| Hybrid lettering tests, 32 cases | 51.14 s | 31.46 s |
| Lettering translation tests, 20 cases | 61.93 s | 28.99 s |

The full runs passed 3,588 and 3,596 tests respectively, with 50 skips each.
These are single-run local observations: the baseline already includes coverage
consolidation and uses original waits and fresh Chromium per operation. Eight
additional cases were collected as work continued in the shared checkout. Module
times sum reported testcase work; the full-suite row uses pytest elapsed time.
The observed full-suite runtime fell by 38%; machine load and cache state affect
the result. The CI split key remains unchanged so Depot learns the new timings.

A subsequent full local gate measured 161.45 s for the serial backend suite.
The four-worker trial measured 60.25 s, with 3,599 passes and 50 skips in both
runs (63% less elapsed time). This is a separate single-run comparison after
the startup/wait improvements above, on the same local machine. Worker testcase
times overlap; compare pytest's elapsed time rather than summing those rows.
The final backend gate also passed its two new source-only runner regressions:
3,601 passes and 50 skips in 53.31 s, with Ruff passing before the suite.

# Test coverage analysis — October 9, 2026

**Historical snapshot.** Measured against commit
`2215da0a925f91cce069b30b40805863cad32b3e` in the shared checkout. This is an
analysis, not a coverage policy or a claim that production integrations passed.
[LCOV and Cobertura reports](2026-10-09-test-coverage/README.md) provide standard
line and branch coverage records for coverage viewers. The supplementary
[machine-readable measurements](2026-10-09-test-coverage-metrics.json) retain
repository-relative per-file counts and tool versions.

## Assessment

Canary has substantial regression coverage around artifact authority, billing,
authorization, cancellation, and recovery. The main opportunity is to exercise
more integration boundaries and failure branches, rather than increase test
count indiscriminately. A real queue restart test exists but is not wired into
the checked-in CI jobs. Frontend mocks also leave several API and query paths
unexecuted despite extensive room/component tests.

There is no configured coverage collection, uploaded coverage artifact, or
coverage threshold in the reviewed package configurations and
[CI workflow](../../.depot/workflows/ci.yml). Passing tests currently establish
the selected assertions; they do not prevent coverage from declining.

## Measured baseline

| Scope | Passing tests | Skips | Executable lines covered | Branch outcomes covered |
| --- | ---: | ---: | ---: | ---: |
| Application Python | 3,695 | 63 | 31,211 / 35,533 — **87.84%** | 8,757 / 11,280 — **77.63%** |
| Frontend TypeScript/TSX | 1,070 | 0 | 7,474 / 9,401 — **79.50%** | 9,442 / 12,681 — **74.46%** |
| Gateway handlers | 201 in the gateway run | 0 | 1,300 / 1,774 — **73.28%** | 407 / 728 — **55.91%** |

The gateway-handler percentages combine execution from the backend and gateway
runs. The 201 tests comprise `litellm/tests` and the three handler test files;
they also test installed SDK behavior outside the measured handler sources.
Counts are not disjoint coverage contributions and should not be summed into
a repository-wide percentage. Python and V8 branch definitions also differ.
Percentages above are recomputed from counts and rounded to two decimals;
Vitest's own display truncates some values.

The inventory contains 186 backend test modules and 2,556 test functions before
parameter expansion, 138 frontend test files, five gateway dependency test
files, and three handler test files. Coverage includes 227 application Python
files, eight handler Python files, and 279 frontend files, including empty
modules. The existing backend audit found no repeated JUnit identities and no
exact AST duplicate candidates. That does not establish that all assertions
are distinct; see [backend test maintenance](../reference/backend-tests.md).

The 63 backend skips break down as follows:

| Reason | Cases | Interpretation |
| --- | ---: | --- |
| PostgreSQL ledger, authorization, purchase/account outbox, tester tracker | 41 | Separate disposable-database CI job selects these suites; not executed in this local analysis. |
| Real PostgreSQL durable queue restart | 1 | Existing test is not selected/configured by the database CI job. |
| Built public pages and SPA mounts | 17 | Deliberately hidden by the source-only backend runner. A separate local run with the existing build passed all 37 cases in these two modules. |
| Removed raw transport or filename semantics | 4 | Explicitly marked obsolete tests remain collected; review/remove them if their replacement assertions remain sufficient. |

All five frontend production hydration cases ran using the existing `web/dist`
build. No new build was produced for this analysis. The built-page backend
follow-up was not added to the coverage baseline. The full release gate,
disposable database job, container startup checks, and live providers were not
run. Local Node was 22.22.3, below the declared Node 24 range; frontend results
are useful local evidence but do not replace the pinned CI environment.

## Contracts with useful existing evidence

| Contract | Representative tests | What they establish |
| --- | --- | --- |
| Series and artifact authority | `test_series_parts.py`, `test_story_bible_edits.py`, `test_series_artifact_concurrency.py` | Adapt freezes text; stale revisions fail; adapted citations survive edits; shared style changes invalidate dependent Finish work. |
| Paid work and ambiguity | `test_credit_call_authorization.py`, `test_pipeline_failure_boundaries.py`, `test_page_fallback.py`, `test_asset_route_fallback.py` | Rejected work preserves artifacts; holds survive ambiguous outcomes; the approved OpenAI/FAL exception retains absorbed-attempt provenance. |
| Frozen requests and tenant boundaries | `test_frozen_requests.py`, `test_security_boundary_contracts.py` | Snapshots survive source mutation; corrupted manifests and symlinks fail closed; signed-token authority and cross-tenant paths are checked. |
| Page recovery and visual evidence | `test_page_recovery_routes.py`, `test_page_review.py`, `pageCheckRecovery.test.tsx` | Cached evidence avoids new spend; stale render consent is rejected; changing artwork does not inherit verification. |
| Lettering independence | `test_hybrid_lettering.py`, `test_lettering_translation.py`, `letteringEditor.test.tsx` | Real Chromium rendering, independent display copy, optimistic revisions, recoverable drafts, and Finish invalidation have coverage. |
| UI state and provider serialization | `pipelineStart.test.tsx`, `pipelineReconnect.test.ts`, `litellm/tests/test_gateway_contracts.py`, `test_vertex_multimodal.py` | Admission acceptance controls running state; reconnect behavior and installed/patched SDK request/response contracts are exercised. |

These are representative reviewed tests, not an exhaustive requirements matrix.
Many tests inject provider responses or dispatch transports. They protect
deterministic contracts, but do not demonstrate model output quality, real
payment completion, or a complete browser-to-worker-to-export journey.

## Gaps and priorities

1. **Wire the real queue restart test into a disposable PostgreSQL gate.**
   `test_durable_queue.py::test_postgres_restart_fifo_and_no_ambiguous_redelivery`
   requires `CANARY_TEST_QUEUE_DSN`. The database job sets
   `CREDIT_TEST_DATABASE_URL` and selects five other modules; backend shards
   also lack the queue DSN. Thus neither configured path runs this test.
   It checks FIFO after restart and prevents ambiguous/terminal redelivery,
   a more valuable release guarantee than a higher global percentage.
   Use the queue's required disposable schema/setup and assert the case ran
   rather than silently skipped. `server/durable_queue.py` currently reaches
   75.38% of lines and 68.57% of branches.
2. **Cover the frontend API/query boundary with real wrappers.**
   `api/queries.ts` reaches 30.00% of lines, `api/pages.ts` 20.93%, and
   `api/operator.ts` 0%. Room/component tests often mock these boundaries;
   for example, `operatorModelPanel.test.tsx` replaces the operator API.
   Add focused tests that retain real wrappers/hooks and replace only HTTP:
   part/series URL scope, paid-action flags, request bodies, stale consent,
   query invalidation, and failure recovery. All frontend API files together
   cover 444 / 846 lines and 327 / 525 branches.
3. **Exercise the assembled backoffice UI.**
   `BackofficePage.tsx` has 0 / 194 executable lines and 0 / 315 branches
   covered. Child panels and backend operator routes have tests, but those do
   not exercise connection/token handling, snapshot loading, or credit-grant
   outcomes in the assembled page. Backend `routers/backoffice.py` reaches
   54.24% of lines and 35.07% of branches. Prioritize denied access, connection
   failures, live/sandbox indicators, and successful/failed grant refreshes.
4. **Close valuable failure branches in generation and gateway code.**
   Cast (`stages/s3_cast.py`) has 207 missing lines; page routes have 188;
   frozen requests have 163. Gateway handlers have 321 missing branch outcomes,
   with `vertex_multimodal.py` at 48.97% branch coverage and `fal_provider.py`
   at 56.41%. Review uncovered outcomes for malformed output, cancelled work,
   ambiguous submissions, provenance persistence, and reference overflow.
   Add provider-free assertions for distinct contracts; do not repeat the
   same generic transport failure across every model alias.
5. **Add a small browser journey layer and repeatable coverage reporting.**
   The reviewed web configuration runs jsdom tests; backend Chromium tests
   exercise the lettering renderer. No configured application-browser E2E
   job was found. A deterministic, provider-free journey through creation,
   checkpoint approval, queued work/reconnect, lettering save, and export
   would test wiring that component and route tests cannot establish alone.
   Persist branch reports in CI first; then establish per-area/diff targets
   after classifying unreachable or unused code. Avoid an arbitrary global
   threshold that rewards low-risk tests over recovery and billing checks.

Other measured gaps merit classification before adding tests:
`clients/api_logging.py` has 0 / 134 lines covered and no references found in
the searched application/handler Python sources. Determine whether it is
retained external functionality or unused code. Frontend zero-coverage files
also include entry/bootstrap modules and small controls; a zero does not by
itself establish a missing product contract.

## Core pipeline detail

| Module | Lines | Branches |
| --- | ---: | ---: |
| `book_adaptation.py` | 93.65% | 88.68% |
| `page_planning.py` | 94.76% | 87.24% |
| `page_drawing.py` | 88.13% | 78.37% |
| `page_review.py` | 87.22% | 75.72% |
| `page_finishing.py` | 87.10% | 77.32% |

The lower branch results are the stronger signal for focused follow-up.
Executed lines do not establish assertion quality, narrative quality, image
fidelity, or visual review. The existing 66 Python excluded lines retain their
normal coverage exclusions; this analysis added no exclusions to improve scores.

## Reproduction and measurement limits

Coverage tools were installed temporarily outside the repo: `coverage==7.10.7`,
`pytest-cov==7.0.0`, and `@vitest/coverage-v8@5.0.1`. No manifests, lockfiles,
coverage gates, servers, or test contracts were changed. With the Python tools
available to each interpreter and the matching V8 provider resolvable by Vitest,
run from the repo root:

```sh
COVERAGE_FILE=/tmp/canary-backend.coverage novel_to_comic/.venv/bin/python \
  scripts/run_backend_checks.py -q -n 4 --dist worksteal -ra \
  --cov=novel_to_comic --cov=litellm_handlers --cov-branch \
  --cov-report=json:/tmp/canary-backend-coverage.json --cov-report= \
  --junitxml=/tmp/canary-backend-tests.xml
COVERAGE_FILE=/tmp/canary-gateway.coverage litellm/.venv/bin/python -m pytest \
  litellm/tests litellm_handlers -q --cov=litellm_handlers --cov-branch \
  --cov-report=json:/tmp/canary-gateway-coverage.json --cov-report=
COVERAGE_FILE=/tmp/canary-combined.coverage novel_to_comic/.venv/bin/python \
  -m coverage combine --keep /tmp/canary-backend.coverage /tmp/canary-gateway.coverage
COVERAGE_FILE=/tmp/canary-combined.coverage novel_to_comic/.venv/bin/python \
  -m coverage json -o /tmp/canary-combined-coverage.json
python3 scripts/audit_backend_tests.py --junit /tmp/canary-backend-tests.xml
```

From `web/`:

```sh
npm test -- --coverage --coverage.provider=v8 \
  --coverage.include='src/**/*.{ts,tsx}' \
  --coverage.exclude='src/__tests__/**' --coverage.exclude='src/test/**' \
  --coverage.exclude='src/**/*.d.ts' \
  --coverage.reporter=json-summary --coverage.reporter=json \
  --coverage.reportsDirectory=/tmp/canary-web-coverage
```

For Python totals, select application source and handler source from the
combined JSON and omit handler `test_*.py` files. For each area, sum covered
and total counts before computing percentages; do not average file percentages.
The checked-in metrics retain these filtered counts. Frontend includes all
matching source files, including unimported files, rather than only files
reached by tests.

The shared JavaScript lettering engine outside `web/src`, deployment scripts,
shell tooling, and installed third-party gateway code are not in these source
denominators even where tests exercise them. No mutation testing or live output
evaluation was performed. The first sandboxed backend run failed on Chromium
Mach-port registration and local process/network restrictions; its results
were discarded in favor of the clean run with local process access. Instrumented
runtime is not a comparable performance baseline.

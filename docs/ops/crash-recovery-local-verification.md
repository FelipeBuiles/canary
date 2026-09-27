# Crash recovery: local verification

Status: Local evidence, recorded 2026-09-10. Not deployed verification.

The final combined backend selection passed **243 tests**, with **12 skips**.
The separately authorized loopback monitor suite passed **7 tests**. Documentation
reliability, entrypoint shell syntax and `git diff --check` passed.

The combined selection was (historical command: `test_image_langfuse.py` was
retired in the PostHog migration; current telemetry coverage is in `test_posthog.py`):

```sh
novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_ai_client.py novel_to_comic/tests/test_litellm_http.py novel_to_comic/tests/test_complete_page_draw.py novel_to_comic/tests/test_image_failure.py novel_to_comic/tests/test_image_langfuse.py novel_to_comic/tests/test_crash_fault_injection.py novel_to_comic/tests/test_entrypoint.py novel_to_comic/tests/test_launch_safety.py novel_to_comic/tests/test_page_recovery_routes.py novel_to_comic/tests/test_server_admission.py novel_to_comic/tests/test_export_router.py novel_to_comic/tests/test_credited_job.py novel_to_comic/tests/test_operations.py novel_to_comic/tests/test_page_finishing.py novel_to_comic/tests/test_generation_jobs.py novel_to_comic/tests/test_credit_ledger_postgres.py novel_to_comic/tests/test_spa_static.py -q
novel_to_comic/.venv/bin/python -m pytest novel_to_comic/tests/test_operations_monitor.py -q
```

Evidence includes:

- Four real child-process hard exits: before submission, after submission before
  response, after saved Draw output before settlement, and during export.
  Durable SQLite journals and page artifacts are real; provider/accounting calls
  are doubles. Replayed HTTP actions never redispatch, saved artwork remains,
  and recovery does not release holds or submit another paid request.
- Caught timeout, cancellation, protocol/encoding failure, gateway failure and
  accepted-response decode failure retain ambiguous holds. Known refusals keep
  their existing semantics. Saved-result and settlement-idempotency regressions
  remain part of the relevant suites.
- Subprocess supervisor tests cover unexpected exits, successful recovery,
  deliberate signals, gateway degradation, persistent budgets and exhaustion.
- External monitor tests cover a stopped local HTTP server, sustained readiness
  failure, repeated observations across monitor restart, meaningful updates,
  resolution, bounded maintenance, source-contract guidance, credential handling,
  redaction and mocked delivery failures. Missing evidence or maintenance
  suppression does not manufacture recovery.

Eight skipped tests require an explicitly isolated PostgreSQL database. Docker
inspection approval was cancelled; no database or container was created, and
real PostgreSQL ledger behavior was not verified in this task. Four additional
skips are existing obsolete raw-image tests with provider-wire replacements.

No deployment, provider spend, or live notification delivery occurred. The
external monitor still needs independent hosting, durable storage and a
separately authorized notification receiver. A hard-killed supervisor may not
record its final exhausted budget; its external availability incident directs
the operator to Fly events and durable recovery state, without guessing why the
Machine stopped. Fly retry timing, actual deliberate-stop behavior and live
alert receipt remain activation checks in the [runbook](crash-recovery.md).

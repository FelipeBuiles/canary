# Customer-facing deployment

Status: Current

1. If the release includes a database change, review and apply it manually
   using `docs/deploy.md`; confirm a current backup and record the result.
2. Announce the maintenance window and stop new generation intake.
3. Push the exact release SHA to `main`.
4. Manually run the `CI` workflow against `main`. The dispatch confirms the
   maintenance window is active.
5. Wait for the backend, frontend, and Docker jobs to pass. CI then starts the
   `Deploy production` job for that same SHA.
6. CI checks that generation is idle, records the rollback release, deploys,
   and verifies the public release contracts. CI has no production database
   credential and never applies schema changes.
7. Copy `release-evidence-template.md` and attach the CI job summary.
8. Run a signed-in smoke test, record the result, and reopen work.

# CI and releases on Depot

GitHub hosts the personal repository, sends push/PR events through Depot Code
Access, and displays Depot's checks. All tests, image builds, and deployment
commands run in `.depot/workflows/ci.yml` on Depot CI. No GitHub Actions runner,
API bridge, or GitHub `DEPOT_TOKEN` secret is required for the final architecture.

## Release flow

For a push to main (or a manual Depot dispatch on main):

1. Backend, frontend, gateway, tooling, and PostgreSQL security/billing checks
   run in parallel with the production image build.
2. The image job builds and pushes a uniquely tagged release to Fly's registry
   and smoke-tests it using its immutable digest. BuildKit's cache persists in
   Depot container-build project `js338b6zll` (`canary`).
3. Deployment waits for all five checks and the image job to succeed, then takes
   the `production-deploy` concurrency lock. Running deployments are not cancelled.
4. It drains production, records rollback information, deploys the exact tested
   image digest, and verifies the expected source SHA before resuming admissions.
   A drain or verification failure preserves the existing failure behavior.

PRs run the five check jobs and a Docker smoke build with placeholder configuration.
They never run the production image or deployment job. Main releases build only
one application image; they do not repeat the PR smoke image build. Vitest uses
8 CPUs; four backend shards use 2 CPUs each; gateway, PostgreSQL, tooling,
deployment, and remote-build client jobs use 2 each. All runners use Ubuntu
24.04 x86_64. Container compilation runs on Depot's separate persistent builder.

## Speed and cache behavior

- Backend files are split across four isolated jobs by `depot tests run`.
  Every shard reports JUnit timings with `junit_family=xunit1` to retain filename
  identities. The stable split key is `canary-backend-py312`. Later runs use those
  timings to balance the workload. Full-page contracts remain part of the suite;
  audits, documentation checks, and Ruff run once, on shard zero.
- Release SHA, timestamp, and frontend configuration arguments appear after
  dependency installation in the Dockerfile. Changing release metadata rebuilds
  the frontend bundle and final image metadata, while dependency layers remain
  eligible for reuse. Application source installation also follows the independent
  gateway dependencies and Prisma generation, preserving them across app changes.
- App and gateway images use the remote Depot builder and its persistent 50 GiB
  cache per architecture, retained for 14 days. There is no GitHub Actions cache
  export/import. Depot CI supplies short-lived builder authentication automatically.
- Test jobs start from the `canary-ci:py312-node24.21-pw1.63-v1` runner snapshot in
  `6ntrqswcbt.registry.depot.dev`. It contains Python 3.12, Node 24.21.0, uv
  0.12.17, Playwright 1.63.0 Chromium/system libraries, and PostgreSQL tools/image.
  Repository dependencies still install from reviewed lockfiles. Setup actions
  restore tool paths. Browser version mismatches trigger a full install rather
  than silently using incompatible system libraries.

Rebuild the runner snapshot after changing these tool versions, and periodically
to pick up base-image/system updates. Bump its tag in both workflows together:

```sh
depot ci run --workflow .depot/workflows/build-ci-image.yml --job snapshot
```

This setup-only workflow has no checkout or production secrets. Build the new
snapshot before switching consumer jobs to its tag. The image was first published
successfully in Depot run `1jftd54hvg` on 2026-10-06.

See Depot's [test splitting](https://depot.dev/docs/ci/how-to-guides/split-tests),
[custom images](https://depot.dev/docs/ci/how-to-guides/custom-images), and
[remote builder integration](https://depot.dev/docs/container-builds/integrations/depot-ci).

For a repeatable image-cache check with placeholder configuration, run:

```sh
depot ci run --workflow .depot/workflows/benchmark.yml --job docker
```

It builds and loads the image, smoke-tests both Python environments, then changes
release metadata, rebuilds, and verifies the new version inside the loaded image.
It neither publishes a release to Fly nor deploys production.

### Trial measurements (2026-10-06)

| Measurement | Before these optimizations | Optimized trial |
| --- | --- | --- |
| Backend pytest wall time | 227 s, one serial Depot job | 79–98 s per timing-balanced shard, running concurrently |
| Backend job including setup | 267 s | About 2 minutes per shard, excluding retries |
| App build and load on remote builder | 114 s initial cache fill | 41 s from a fresh runner with builder cache |
| Second app build/load on the same runner | — | 11 s with a new release version |

The first successful four-shard run (`75tw6z6hr5`) ran 3,287 tests with 49 skips
and uploaded all four reports. It used file-size balancing (slowest pytest shard:
154 s). Run `cg8s0nx2kx` confirmed historical timing-based balancing across all
169 candidate files. Its first attempt encountered one subprocess timeout in
`test_entrypoint.py`; timings above are observations, not a guaranteed clean-run
latency. Retrying only that shard passed all 1,081 tests (22 skipped), with the
test and its timeout unchanged. All four final shards passed and uploaded reports;
the total remained 3,287 passed and 49 skipped. Frontend (968 tests), gateway
(90 tests plus both startup smoke modes), and PostgreSQL (349 billing/security
regressions plus 40 database contracts) also passed on the new runners.

Image runs `jzznw32gw7`, `0tj0mc0qxw`, and `s6m9v8x5ls` verified cache reuse,
app/gateway imports, and updated runtime release metadata. These are development
trials with placeholder frontend configuration, not production deployment timings.
Earlier baseline runs used an earlier working-tree snapshot and different cache
states, so treat speed comparisons as indicative rather than controlled benchmarks.

## Credentials and production restriction

The following GitHub production environment secrets were imported into
Scenewright's Depot CI secret store on 2026-10-06:

- `FLY_API_TOKEN`, `CANARY_OPS_TOKEN`
- `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`
- `POSTHOG_API_KEY`, `POSTHOG_PROJECT_TOKEN`

`POSTHOG_HOST` and `POSTHOG_PROJECT_ID` variables were also imported.
Each imported value has exactly one variant, scoped to repository `FelipeBuiles/canary`, branch `main`,
workflow `.depot/workflows/ci.yml`, and environment `production`. No unscoped
fallback production variants were present at verification. The two privileged jobs declare
`environment: production` for Depot secret matching.

GitHub's production environment currently allows only main, with no required
reviewer or wait timer. Depot does not enforce GitHub environment protection
rules. Preserve the main restriction through both the job conditions and Depot
secret availability rules. See [secret availability](https://depot.dev/docs/ci/how-to-guides/manage-secrets-and-variables).

## Activation and operation

Scoped credentials have been imported and verified; temporary migration branch
access was removed and GitHub production access is main-only again. Commit the Depot workflow
and removal of both GitHub workflows together so there is one release authority.
Depot registers automatic triggers when the workflow reaches the default branch.
The first main push then runs the complete release. Keep production execution
unverified until that run succeeds. Update any branch protection rules requiring
old GitHub job names to the corresponding `Depot CI / ...` checks.

For manual releases use Depot's dashboard or:

```sh
depot ci dispatch --repo FelipeBuiles/canary --workflow ci.yml --ref main
```

The optional `skip_drain` input is only for operator-directed offline recovery
when production machines are stopped. Never use it for a normal release.

For local changes, select test jobs explicitly; do not run the full release
workflow just to validate local code:

```sh
depot ci run --workflow .depot/workflows/ci.yml --job backend --job web --job gateway --job tooling --job database
```

The CLI patch must include new files (`git add -N <file>` is sufficient). During
this migration, disable Git rename detection for local runs so the move from
`.github` to `.depot` applies correctly:

```sh
GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=diff.renames GIT_CONFIG_VALUE_0=false \
  depot ci run --workflow .depot/workflows/ci.yml --job backend
```

The dedicated GitHub bridge token created during setup is unused and can be
revoked along with the repository's `DEPOT_TOKEN` secret after cutover. Existing
GitHub production secrets can remain as a rollback source during rollout.

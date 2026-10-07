# CI and releases on Depot

GitHub hosts the personal repository, sends push/PR events through Depot Code
Access, and displays Depot's checks. All tests, image builds, and deployment
commands run in `.depot/workflows/ci.yml` on Depot CI. No GitHub Actions runner,
API bridge, or GitHub `DEPOT_TOKEN` secret is required for the final architecture.

## Release flow

For a push to main (or a manual Depot dispatch on main):

1. Backend, frontend, gateway, tooling, and PostgreSQL security/billing checks
   run in parallel with the production image build.
2. The image job builds and saves a uniquely tagged release to Depot's OCI registry
   and smoke-tests it using its immutable digest. BuildKit's cache persists in
   Depot container-build project `js338b6zll` (`canary`).
3. Deployment waits for all five checks and the image job to succeed, then takes
   the `production-deploy` concurrency lock. Running deployments are not cancelled.
4. It requests a host-managed Lightsail release of the exact tested image digest.
   The host drains, records the rollback configuration, replaces the process,
   verifies the source SHA and public contracts, then explicitly resumes.
   Deployment is disabled until the first Lightsail cutover is complete.

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
- Backend lettering tests reuse Chromium processes with fresh contexts for each
  operation. Provider-free billing/security regressions run in the backend shards
  once; the database job owns the real PostgreSQL contracts. The release backend
  command also runs full-page contracts only once, within the full suite. See
  [backend test maintenance](backend-tests.md) for timing reports and trimming rules.
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

## Lightsail deployment configuration

The release destination has changed to Lightsail; Depot still runs tests and
builds. See [Lightsail CI](../ops/lightsail-ci.md) for the dedicated SSH key,
read-only pull tokens, scoped AWS OIDC firewall role, host controller, activation
switches, cancellation semantics and operator recovery.

Frontend build/source-map credentials retain their production availability rules:
repository `FelipeBuiles/canary`, branch `main`, workflow `.depot/workflows/ci.yml`,
environment `production`, with no unscoped variants. The updated workflow does
not use `FLY_API_TOKEN` or `CANARY_OPS_TOKEN`. Existing imported copies are not
removed by this source change and should be retired after the rollback window.
Depot does not enforce GitHub environment protection rules; preserve the job and
secret-availability restrictions. See [secret availability](https://depot.dev/docs/ci/how-to-guides/manage-secrets-and-variables).

## Activation and operation

Publishing this workflow ends automatic Fly deployment. The Lightsail deploy job
skips until `CANARY_DEPLOY_TARGET=lightsail`, and the host independently requires
its `ci-enabled` marker, no maintenance hold, and a running application. Complete
the initial migration and Linux rehearsal before setting these gates.

For a normal manual release after activation:

```sh
depot ci dispatch --repo FelipeBuiles/canary --workflow ci.yml --ref main
```

There is no offline `skip_drain` input. Operator-managed recovery must establish
safe data and queue ownership before starting either platform.

For local changes, select test jobs explicitly rather than invoking deployment:

```sh
depot ci run --workflow .depot/workflows/ci.yml --job backend --job web --job gateway --job tooling --job database
```

The local patch must include new files (`git add -N <file>` is sufficient).
A local provider-free test run is not proof of OIDC, registry, SSH, firewall or
systemd release behavior; those remain part of the isolated Linux rehearsal.

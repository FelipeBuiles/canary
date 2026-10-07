# Local gateway refresh

**Status: Current, October 6, 2026.** Implementation and provider-free tests are
authoritative. This manages the standalone local Compose `litellm` service;
production deployment follows its own deployment runbook.

From any working directory, invoke the script in this checkout:

```sh
./scripts/gateway.sh          # Refresh only what is stale
./scripts/gateway.sh --check  # Read-only: explain whether a refresh is needed
./scripts/gateway.sh --rebuild # Force a rebuild and recreate
```

To refresh the gateway while starting or reusing the development stack:

```sh
./scripts/dev.sh --refresh-gateway
```

Normal API/Codex startup and `dev.sh --check` check gateway freshness, including
the authenticated model inventory. They refuse to reuse a stale gateway and
print the refresh command. They do not restart a running gateway automatically.
`--refresh-gateway` is explicit authorization to refresh it; it cannot be combined
with `--check`, `--no-docker`, or `--mock`. Mock mode needs no gateway refresh.

## What the command detects

| Evidence | Action |
|---|---|
| Loaded files, image, Compose settings, and model routes match | Leave the gateway running |
| Routes, pricing, custom handlers, or metrics callbacks changed since startup | Recreate with the existing image |
| Environment, credential mounts, or other gateway Compose settings changed | Recreate with the existing image |
| Dockerfile, dependency lockfiles, proxy patches, or startup helper changed | Build, then recreate |
| A current image is already built but the container uses an older one | Recreate without another build |
| Gateway is absent or stopped | Start with the current image, building if needed |

The image carries a build fingerprint. Its entrypoint records the contents of
the mounted configuration and Python modules immediately before starting
LiteLLM. Checks compare that frozen record with the checkout, rather than
mistaking updated bind mounts for code the running process loaded. Hashes use
file contents; timestamp-only changes and handler tests do not trigger refreshes.

Images built before this mechanism, or built directly without its fingerprint
argument, need one bootstrap build through `gateway.sh`. Subsequent runs skip
unnecessary work. `--check` exits zero when current and nonzero when stale or
unhealthy. An unavailable model inventory alone reports a readiness problem
instead of blindly restarting a gateway with matching fingerprints.

## Credentials and scope

The script uses the launcher's environment precedence: exported values, then
`web/.env.local`, `web/.env`, and root `.env`. Explicit settings win. When an
existing gateway has credentials or Vertex/AWS mounts absent from these settings,
the command retains them and the existing Compose project/override files.
Missing configured credential mounts stop the refresh before recreating anything.
Secret values remain in process memory and are excluded from command arguments,
fingerprint records, and inspection diagnostics.

Builds complete before the running gateway is replaced; a failed build leaves
it available. The command recreates only `litellm`, reuses its database, and
starts the gateway database if it is missing. It never deletes database volumes,
restarts the backend/frontend, or makes generation requests. After recreation
it waits for the authenticated model inventory and verifies the fingerprints
and every configured model alias.

Run refreshes between generation jobs: replacing the gateway can interrupt an
active provider call. The script does not resume failed jobs or resubmit images.

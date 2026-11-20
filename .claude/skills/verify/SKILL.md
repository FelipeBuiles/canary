---
name: verify
description: Drive the real Canary web app (Vite UI on :5173 over the FastAPI backend on :8000) the way a user does, and capture proof that a change works. Use after changing UI, API routes, room behavior, lettering, reading pages, or anything a user can see; drives only the stack the user already started, never starts or restarts servers.
---

# Verify Canary in the real app

Canary's user surface is the React SPA served by Vite at `http://127.0.0.1:5173`,
proxying `/api` and `/static` to the backend at `http://127.0.0.1:8000`.
Secondary surfaces: the HTTP API itself (`docs/reference/api-routes.md`) and the
backoffice (`/backoffice`, operators only; not mapped).

Three facts shape every run:

1. **You never launch the stack.** The user manages dev servers (AGENTS.md). If
   the doctor fails, stop and ask the user to run `./scripts/dev.sh --mock`
   (zero-cost replay) or tell you it is up. Never run `dev.sh`, `pipeline serve`,
   `npm run dev`, `docker compose`, or `gateway.sh` from this skill.
2. **Supabase is production.** Accounts, credits and project rows live in the
   production Supabase project. Act only as the test account
   (`CANARY_VERIFY_EMAIL`), create nothing a journey does not need, and never
   sign up, buy credits, publish, or touch another account.
3. **Paid routing is the default.** Unless the doctor reports `model_mode=mock`,
   a stage run, draw, redraw, cast/style generation or translation spends real
   money. In non-mock mode, run only read-only journeys. Even in mock mode,
   run generation only on a project whose `config.yaml` has `mock_mode: true`.

## Launch

Nothing to launch. Ready means `bin/doctor.sh` exits 0. If it fails on the
backend or frontend, report the failing line to the user and stop.

## Doctor

Read-only; run first, and again whenever anything looks off:

```bash
.claude/skills/verify/bin/doctor.sh
```

It checks: `/api/health/ready` (`status=ok`, `pipeline_contract=eight-stage-v2`,
`generation_queue=ok`, prints `model_mode` and warns when not `mock`); which
process owns ports 8000/5173/4010; that Vite serves the SPA and proxies
`/api/public-config`; whether Turnstile is configured (blocks scripted sign-in);
whether the test credentials exist (never printed); that `playwright-cli` is
installed. Exit 1 means do not drive.

## Drive

Harness: `playwright-cli` (repo devDependency; full reference in
`.agents/skills/playwright-cli/SKILL.md`). Always use the named session
`canary-verify` so you never touch another browser:

```bash
export PLAYWRIGHT_CLI_SESSION=canary-verify
PW=node_modules/.bin/playwright-cli     # run from the repo root
EV=tmp/verify/$(date -u +%Y%m%dT%H%M%SZ)-<feature>; mkdir -p "$EV"
```

Sign in through the real `/login` form (password never printed; output redacted):

```bash
.claude/skills/verify/bin/signin.sh "$EV"
```

If the doctor warned about Turnstile, scripted sign-in will fail. Ask the user
to sign in once in a headed window, then reuse the saved state:

```bash
$PW open --headed http://127.0.0.1:5173/login     # user signs in as the test account
$PW state-save tmp/verify/auth-state.json          # gitignored; contains a session
# later runs: $PW open http://127.0.0.1:5173/ && $PW state-load tmp/verify/auth-state.json && $PW reload
```

Then drive by route path and accessible name, never coordinates:

```bash
$PW goto http://127.0.0.1:5173/project/<id>/pages
$PW snapshot                         # refs + accessible tree
$PW find "Page gallery"              # locate by aria-label
$PW click <ref>
$PW screenshot --filename="$EV/<step>.png"
```

Lazy routes render after `open`/`goto` returns: wait for a known element
(`$PW run-code 'async page => { await page.getByRole("dialog", { name: "Book reader" }).waitFor(); }'`)
before snapshotting. `run-code` echoes the code it ran, so never inline a
secret in it except through `bin/signin.sh`, which redacts output.

Handles that exist today: login form `form[name="Sign in"]` with labels
`Email` / `Password`; Library heading `#library-title`, button
`New production`, filter group `Show`; room routes
`/project/:id/{story,styles,cast,pages,book,settings}`; Pages room
`Page gallery`, `Filter pages`, `Drawing progress`; lettering editor
`Lettering page canvas`, `Lettering controls`; public reader dialog
`Book reader` with footer (`contentinfo`) `Next page` / `Previous page`,
`Jump to page`, `Close reader`. The per-feature recipes are in `features/`.

Pair the UI with the API to check side effects. `bin/api.sh` fetches from
inside the session's page, adding the Supabase bearer token when it is
signed in, and prints `HTTP <status> signed_in=<bool>` to stderr:

```bash
.claude/skills/verify/bin/api.sh canary-verify /api/projects/<id>/status "$EV/status.json"
```

## Evidence

Everything goes in `tmp/verify/<UTC timestamp>-<feature>/` (gitignored, never
removed by cleanup): screenshots before and after the action, the API JSON
that shows the resulting state, and a `notes.md` naming the commit
(`git rev-parse --short HEAD`, plus `-dirty` if applicable), the doctor's
`model_mode`, and what each file proves.

Proof standards:

- Exercise the real user path: the form, the button, the route. No
  test-only endpoints, no setting React state, no writing artifacts by hand.
- Capture the action and the resulting state, not only the final screen.
- Verify side effects the user cares about through the API or files: status
  JSON, `projects/<user_id>/<slug>/` artifacts (mock projects only), lettering
  revision numbers, `generation_queue`.
- Mocks only at the existing production boundary: the `--mock` replay service
  replaces model providers. Nothing else is mocked.
- A mocked run proves wiring and UI, not image quality (AGENTS.md).

## Cleanup

```bash
.claude/skills/verify/bin/cleanup.sh
```

Closes and deletes only the `canary-verify`, `canary-verify-public` and `canary-verify-neg` browser sessions. It never stops
servers, Docker, or other browsers, and never deletes `tmp/verify/`. If a
journey created data in Supabase (for example a mock project), list it in
`notes.md` and tell the user. Do not delete production rows yourself.

## Helpers

| Script | Use |
| --- | --- |
| `bin/doctor.sh` | Read-only readiness check. Exit 0 = drivable. |
| `bin/signin.sh <evidence-dir>` | Signs `canary-verify` in through `/login` and saves `after-signin.png`. |
| `bin/api.sh <session> </api/path> [out]` | Authenticated in-page GET; exit 0 on 2xx. |
| `bin/cleanup.sh` | Closes the `canary-verify*` sessions it names; keeps evidence. |

## Feature map

`features/README.md` indexes user-facing features and how to prove each one.
When a change touches a mapped feature, drive every entry point the map lists,
not the most convenient one. Keep the map current with `/maintain-verification-skill`.

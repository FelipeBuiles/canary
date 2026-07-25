# Scenewright — Launch Readiness

> Current-state review, updated 2026-07-13. This document is the launch gate;
> [the deploy runbook](../deploy.md) is the operational procedure and
> [the pricing proposal](pricing-and-margin.md) is the current-pipeline
> unit-economics decision. Full-page economics must be revalidated before that
> architecture launches.

## Verdict

**The four code-level launch blockers are fixed in the current working tree.**
They were:

1. `public.user_credits` may bypass RLS because it is a normal owner-executed
   Postgres view granted to `authenticated`.
2. `/api/health/ready` returns HTTP 200 even when Supabase or LiteLLM is down,
   so Fly continues routing traffic to an unhealthy machine.
3. The unauthenticated Stripe webhook is exempt from the request-body limit and
   buffers the complete payload in memory.
4. Stripe credits every `checkout.session.completed` event without verifying
   that `payment_status == "paid"`.

Do not invite external testers yet: the changes are uncommitted/unpushed, the
Supabase schema change has not been applied to the production project, and the
Fly app still has no deployed machine. A **private deployed smoke test** is the
next step after a green CI run for the exact release revision. An **invite-only
soft launch** additionally requires production configuration, monitoring,
backups, two-user authorization tests, and a complete paid end-to-end run.

## Current evidence

### Repository

- Backend lint is green; the full backend suite passes: **1,052 passed, 9
  skipped** on 2026-07-13.
- Frontend ESLint is green, **287 web tests pass** on Node 22.22.3, and the
  production web build succeeds.
- `main` is currently 13 commits ahead of `origin/main`, and there are additional
  uncommitted compose-editor changes. The latest remote CI success is for
  `787f042`, not the current local revision.
- CI runs Ruff, pytest, a high-severity production dependency audit, frontend
  ESLint, Vitest, the frontend build, and a production Docker build. Deployment
  remains manual; this is **CI, not CD**.
- The npm production dependency audit reports **0 vulnerabilities** after
  updating React Router and `ws` to patched lockfile versions.

### Fly.io account

Observed on 2026-07-13:

- `canary-web` exists, but has **no deployed image, machine, or health check**.
- Eleven secrets are staged and undeployed. They do not include Sentry or every
  optional provider key. Pricing/margin policy is now explicit non-secret Fly
  configuration.
- `canary_projects` exists in `iad`, encrypted, at **1 GB**. Scheduled daily
  snapshots are active with five-day retention. A 1 GB volume is too small for
  more than minimal testing and should be expanded before an invited launch.

This means the repository contains deployment artifacts, but there is not yet a
real environment to call launch-ready.

## Architecture now

The old two-Fly-app plan is retired. Production is one Fly app and one 4 GB
machine:

```text
canary-web container
├── uvicorn / FastAPI       0.0.0.0:8000 (public through Fly TLS)
├── LiteLLM subprocess     127.0.0.1:4000 (loopback only)
└── /projects              encrypted Fly volume
```

`litellm/entrypoint.sh` boots LiteLLM, waits for liveliness, and then starts
uvicorn. The gateway is not publicly exposed, but both processes inherit the
container environment; provider keys are **not process-isolated** from the web
process. One worker and one machine remain mandatory because job queues, SSE
state, semaphores, and project files are local.

The canonical deployment details are in [docs/deploy.md](../deploy.md). Do not
reintroduce `fly.litellm.toml`, `Dockerfile.litellm`, or sibling-app instructions.

## Controls already implemented

| Area | Status | Evidence / residual risk |
|---|---|---|
| Auth | Implemented | Supabase JWT signature, expiry, and production audience checks; HttpOnly, Secure, SameSite=Lax session cookie. |
| Project authorization | Code fixed; deployment validation pending | Backend project resolution scopes queries by authenticated user. `user_credits` now uses caller-context RLS; apply the schema and run the two-user test below. |
| Credits ledger | Implemented | Atomic reservations, release-on-failure/startup recovery, database uniqueness for payment IDs. |
| Billing packages | Implemented | Starter/Standard/Creator/Studio packages match the pricing proposal; Fly config pins markup `2.0`. |
| Upload/project caps | Implemented | Novel upload defaults to 10 MB; project cap defaults to 25. Expanded EPUB/PDF resource use remains unbounded. |
| Rate limiting | Implemented with residual risk | Creation, run, regeneration, import, cover, and export paths are limited. Limits are per-IP and process-local; there is no per-user expensive-job concurrency limit. |
| Sentry | Code-ready only | Backend/frontend integrations exist and scrub auth data. No deployed DSN or alert is proven. |
| Readiness | Fixed | Dependency failure returns HTTP 503; missing/partial production configuration fails closed. |
| Legal pages | Implemented; operations pending | Terms, Privacy, AUP, signup assent, and Stripe consent support exist. `legal@` monitoring and deletion/export procedures are not proven. |
| Labs | Closed by default | `CANARY_LABS_ENABLED` defaults false. The short-story endpoints remain on the always-mounted projects router. |
| CI | Implemented | Test/lint/build/Docker gate exists. There is no automatic deployment job. |

## P0 — fixed in the working tree; release validation pending

### 1. Make the credit-balance view honor RLS

Previously, `docs/supabase-schema.sql` created `public.user_credits` as a normal
view and granted it to every authenticated user. On PostgreSQL, a normal view
normally uses the view owner's privileges, which can bypass RLS on
`credit_ledger`.

**Fixed:** the canonical schema recreates the view with
`security_invoker=true`. Apply it to the deployed Supabase project. Then test
with two real Supabase
users that each can read only their own balance and cannot read the other user's
projects, ledger entries, usage events, or balance. Test the Supabase REST API
directly, not only the FastAPI routes.

### 2. Make readiness fail closed

Previously, `GET /api/health/ready` returned a JSON error with HTTP 200, so
Fly's HTTP check considered the machine healthy. It also reported missing
dependencies as `skipped`, including in production.

**Fixed:** dependency failure now returns HTTP 503. In production, missing or
partial Supabase and LiteLLM configuration also returns 503. Tests cover the
status contract. Confirm the Fly health check becomes healthy only when both
dependencies report `ok`.

### 3. Bound the Stripe webhook body

`/api/billing/webhook` is public by design and verifies Stripe signatures.
Previously, signature verification happened only after `request.body()`
buffered the entire body, and the route was exempt from the global 2 MB cap.

**Fixed:** the route enforces a 256 KiB default cap for declared and chunked
bodies while preserving the exact raw signature bytes. The global body cap also
applies. Oversized and byte-preservation tests are present.

### 4. Credit only paid Stripe sessions

Previously, `_handle_checkout_completed` trusted the event type and metadata
without inspecting `payment_status`. Signature verification proves that Stripe
sent the event; it does not prove that funds were collected.

**Fixed:** unpaid or missing-payment-intent sessions are ignored. Paid inserts
use atomic `ON CONFLICT DO NOTHING` semantics keyed by payment intent, so
concurrent duplicate deliveries cannot double-credit or return a uniqueness
error. Paid, unpaid, missing-status, missing-intent, and duplicate paths are
covered.

### 5. Produce a green release revision

Push the intended release revision and require all CI jobs to pass for that SHA.
Local lint, backend tests, frontend tests, and the production build are now
green; CI includes frontend lint. Do not deploy the current dirty working tree.

## P1 — finish before invite-only soft launch

### Production configuration

- Fly config now pins `PULP_MODEL_COST_MARKUP=2.0`,
  `PULP_CREDITS_PER_PROVIDER_USD=100`, and
  `AI_BILL_FAILED_REQUESTS=provider_usage_only`.
- Fly config now pins `CANARY_ALLOWED_HOSTS` and `SCENEWRIGHT_APP_URL` for the
  Fly hostname. Update both when the custom domain is introduced.
- Stripe return URLs now use `SCENEWRIGHT_APP_URL`, require HTTPS in production,
  and never reflect an arbitrary request `Origin`.
- Provision real backend/frontend Sentry DSNs, verify a scrubbed test event, and
  create an error alert. Invalid Sentry configuration now logs and disables
  Sentry without preventing boot.
- OTel is explicitly disabled in Fly config until the production image installs
  the optional dependency and a real export is verified.
- The Docker frontend stage now uses `npm ci`, matching CI and the lockfile.
- Keep Labs off. Decide whether the public short-story catalog/import belongs in
  the launch product; if retained, cap downloaded bytes and decompressed text.
- Expand the 1 GB volume before real projects. Keep automatic snapshots enabled,
  increase retention if required, and perform one restore drill. Snapshots are
  not a substitute for an off-provider backup of exports or project data.

### Billing and auth operations

- Use Stripe test mode first. Verify Checkout → signed webhook → exactly-once
  ledger credit → visible balance, including a duplicate webhook replay.
- Configure the production Supabase Site URL and redirect allowlist, including
  `/reset-password`. Enable email confirmation, custom SMTP, auth abuse controls,
  and CAPTCHA/bot protection appropriate to public signup.
- Set `SCENEWRIGHT_TERMS_URL` and publish the same URL in Stripe so checkout
  consent is actually collected.
- Make `legal@scenewright.ink` and the support address real and monitored. Write
  minimal runbooks for abuse/DMCA handling, account deletion, data export, and
  snapshot retention after deletion. The legal templates should be reviewed by
  counsel before a broad public launch.

### Abuse and browser hardening

- Add a decompressed-size/page/text/time budget for EPUB/PDF extraction; a 10 MB
  compressed upload can still expand into a resource-exhaustion payload.
- Verify Fly's forwarded-client-IP behavior cannot be spoofed to bypass SlowAPI.
  Monitor per-user concurrent generation and add a ceiling if one tester can
  monopolize workers or accidentally drain their balance.
- Add a production security-header policy: CSP, HSTS, `X-Content-Type-Options`,
  `Referrer-Policy`, and a deliberate frame-ancestors policy.

## Deployed acceptance test

Use a separate Supabase project and Stripe test mode for the first deployment.
Do not switch to live purchases until this checklist passes.

- [ ] Release SHA is pushed and every CI job is green.
- [ ] Docker image boots on the 4 GB Fly machine and remains healthy beyond the
      one-minute grace period.
- [ ] `/api/health/ready` returns 200 only when Supabase and LiteLLM both report
      `ok`; dependency failure returns 503. No check is `skipped` in production.
- [ ] Signup, confirmation, login, logout, forgot-password, and reset-password
      work on the deployed domain.
- [ ] Two-user direct-Supabase authorization test passes.
- [ ] Upload a representative EPUB/PDF and complete all nine backend stages,
      including panel regeneration, compose editing, and PDF/CBZ export.
- [ ] Verify estimates, reservations, final debits, refunds/releases, and displayed
      `~N credits` agree for a complete project.
- [ ] Stripe test purchase credits the ledger exactly once; duplicate webhook
      delivery is harmless; unpaid/invalid/oversized events do not credit.
- [ ] Kill the machine mid-draw; confirm stale reservations release and the user
      can recover through `/reset-stale` without being charged for lost work.
- [ ] Sentry receives a scrubbed test error and an alert reaches the operator.
- [ ] Restore the volume from a snapshot and open/export a recovered project.
- [ ] Test narrow mobile, desktop, refresh/deep links, browser back/forward,
      expired sessions, insufficient credits, provider refusal, timeout, quota,
      partial draw failure, and retry flows.
- [ ] Smoke-test English, Spanish, and French. If translation coverage is not
      complete, explicitly launch the soft test as English-only.

## Product-quality gate

The July image-request hardening materially improves prompt/reference ordering,
provider transport, provenance, and failure states. The current eight-panel
benchmark is encouraging, but alternate/significant/restored/location state
coverage and paired acceptance remain incomplete, and wardrobe drift was still
observed.

For a soft launch, either finish those targeted visual evaluations or record an
explicit waiver and recruit testers with the expectation that consistency is
the primary research question. Do not market full-book visual consistency as a
settled claim until real deployed runs support it.

## Accepted soft-launch constraints

These are not blockers for a small invite-only test if they are documented and
monitored:

- One Fly machine, one uvicorn worker, process-local queue/SSE/rate limits.
- In-flight generation is lost on restart; reservations are released and work is
  manually recoverable.
- Project storage is local to one Fly volume; horizontal scaling waits for an
  external queue and object storage.
- Manual deployment. Automatic CD is optional; a green CI gate and a repeatable
  manual deploy are sufficient at this scale.
- Provider safety filters plus the report channel, without a separate input
  moderation stage.

## Go / no-go rule

- **Private deployed smoke test:** go after the four P0 code defects are fixed
  and the release revision is green.
- **Invite-only soft launch:** go after every P1 operational item relevant to the
  selected scope and the deployed acceptance test pass.
- **Public signup / live Stripe:** no-go until email abuse controls, legal/support
  operations, browser security headers, extraction limits, monitoring, and
  backup recovery are proven.
sup

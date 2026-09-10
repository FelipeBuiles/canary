# Scenewright — Launch readiness

**Status: Current repository assessment, September 9, 2026.** Production state
was not inspected for this refresh. Passing local tests or finding a control in
code does not establish that the deployed release, database, alerts, or backups
have it. The July 13 snapshot and
[July 30 reassessment](../research/2026-07-30-market-and-launch-readiness.md)
are historical evidence, not today's release verdict.

## Decision

Build toward a **bounded self-service paid launch**: the customer makes the
creative decisions; software handles routine progress, payment accounting,
recovery guidance, and release checks. Operator intervention should be an
exception measured as a product defect or an explicit billing/support case.
A permanently operator-assisted pilot would conceal the work this strategy
needs to eliminate.

**Repository controls are substantially stronger than the July checklist.
Public paid acquisition is not yet justified by the evidence reviewed here.**
The remaining gate is a dated production evidence package and measured customer
completion, not another blanket rewrite or an infrastructure migration. Keep
paid traffic off until the gates below pass. A private proof exercise can
establish those gates; live purchases and provider spend need their own release
and budget authorization.

## What changed since July

| July assertion | Current repository truth | Evidence |
|---|---|---|
| CI exists, deployment is entirely manual | A manual `CI` dispatch on `main` gates deployment on backend/web/Docker jobs, drains admission, deploys the same source SHA, and verifies public release contracts. Database changes remain manual. | `.github/workflows/ci.yml`, `scripts/check_deploy_safe.py`, `scripts/verify_deployment.py` |
| Missing browser security headers | Production middleware sets CSP, HSTS, content-type, referrer, and permissions policies. Tests cover success/error responses; confirm the public proxy preserves them. | `server/security_headers.py`, `tests/test_launch_safety.py` |
| EPUB/PDF expansion and remote imports are unbounded | Shared upload, page/document, extracted-character, archive-expansion, remote-download, and elapsed-time budgets exist. The elapsed-time check is cooperative, not a hard parser process deadline. | `input_limits.py`, `server/routers/projects.py`, `tests/test_input_limits.py` |
| No per-user generation ceiling | Active generation has a process-local user semaphore (default one); queued jobs requeue fairly and pipeline work shares the semaphore. This is not a distributed admission system. | `server/generation_jobs.py`, `server/routers/pipeline.py` |
| A restart loses all job evidence; release all reservations | Persistent action/job journals and Draw recovery records retain evidence. Interrupted work is shown as recoverable, never automatically requeued. Only expired, never-started owned holds reclaim automatically; started/ambiguous work requires reconciliation. | `server/admission.py`, `server/credited_job.py`, `server/credits.py`, [stage contracts](../reference/stage-contracts.md) |
| Readiness controls Fly routing | Fly routes on process-local `/api/health`. `/api/health/ready` separately checks dependencies and fails closed with HTTP 503 in production. | `fly.toml`, `server/app.py` |
| No deployed machine / 1 GB volume / branch ahead by 13 commits | Those were July 13 observations. No current account, volume, branch-release relationship, or production migration was verified here. | Obtain fresh deployment evidence; do not repeat historical state as current. |

Python paths in this document are relative to
`novel_to_comic/src/novel_to_comic/`; test paths are relative to
`novel_to_comic/`.

The older four security/billing fixes remain implemented: caller-context
`user_credits` RLS in the canonical SQL, readiness HTTP status handling,
bounded raw Stripe webhook bodies, and paid-only/idempotent credit inserts.
They still require production exercises. Code support for refunds, support
runbooks, legal pages, and Sentry also exists; an exercise and an alert reaching
a real operator remain different evidence.

## Gate 1 — money, accounts, and recovery

For one exact release SHA, record these results in a copy of the
[release evidence template](../ops/release-evidence-template.md):

- [ ] Exact-SHA CI succeeds; deployed `/api/version` matches; rollback image and
      compatible database state are recorded. Preserve the `/projects` volume
      including `.request-journal.sqlite3` and Draw recovery records.
- [ ] Canonical Supabase schema is applied and verified. Two independent real
      users cannot read each other's projects, balances, ledger, or usage via
      either application routes or direct Supabase REST access.
- [ ] Signup, confirmation, login/logout, reset emails, production redirects,
      SMTP delivery, and abuse controls work on the public domain.
- [ ] Stripe test Checkout → signed webhook → one credit grant → displayed
      balance works, including duplicate delivery, unpaid rejection, and the
      operator refund/reconciliation path. Record the selected live/test mode.
- [ ] Estimates, holds, renewal, provider usage, settled credits, and released
      credits reconcile for a complete project. Unknown usage is not zero cost.
- [ ] In an isolated, authorized recovery exercise, interruption preserves the
      original action and saved artwork, refresh shows the durable job outcome,
      and recovery cannot silently duplicate a paid image submission. Prove
      cached OCR recovery separately from explicit paid OCR-only recovery.
- [ ] Restore a backup into an isolated environment; recover journals, source,
      references, complete pages, and PDF/CBZ exports. Confirm isolation and
      record recovery time and the actual recoverable point in time.

Neither `/reset-stale`, lease expiry, nor a new image revision proves an
interrupted provider action was free. OCR proves lettering checks only; visual
issues need visual review. Do not reopen traffic after a failed deploy merely
because a status-only idle observation looks safe: establish authenticated drain
before idle and explicitly decide when to resume.

## Gate 2 — a customer can finish without a concierge

Use the real eight-stage path:
`extract → brief → style → cast → adapt → plan → draw → finish`.
The customer still approves Brief, chooses Style, approves Cast, and continues
from Draw. Hands-off operation does not mean silently accepting creative
choices or authorizing new paid work.

- [ ] A new account can understand the offer, purchase the published pack,
      upload a rights-cleared source, see the next estimate, and start analysis
      without a founder call or manual credit grant.
- [ ] First-run guidance, empty states, error messages, expired sessions,
      insufficient balance, explicit Resume after top-up, browser refresh,
      navigation, and narrow mobile layout all work on the deployed release.
- [ ] Finish a bounded source through complete-page Draw and PDF/CBZ export.
      Inspect visible lettering, recurring identities, style, and source
      fidelity. Record corrective attempts and rejected outputs as well as the
      selected showcase. A successful download request is not proof that a
      browser finished downloading or that the book is publish-ready.
- [ ] The same path succeeds for independent authors without the operator
      rewriting prompts, repairing files, advancing checkpoints, or manually
      settling ordinary jobs. Record every intervention and fix recurring ones.
- [ ] Published examples are real outputs with source rights, generation/model
      provenance, explicit development/customer labels, and permission to show
      customer material. Do not substitute style references for finished-page
      evidence or fabricate testimonials.

## Gate 3 — unattended operation and bounded acquisition

These are **proposed acceptance criteria**, not implemented automation or
measured service levels. Set the initial traffic/spend cap from measured
capacity, full-project economics, and the launch campaign decision before
turning on acquisition.

| Priority | Work that removes recurring operator labor | Acceptance evidence |
|---|---|---|
| P0 | Recover from a web/container crash while preserving deliberate maintenance stops | The current Fly `restart = never`, disabled autostart, and single Machine mean web/container failure needs an operator. Design and exercise bounded restart supervision with explicit maintenance state; do not blindly enable restarts or auto-retry paid jobs. LiteLLM child restart already has a bounded budget. |
| P0 | Actionable monitoring and reconciliation queue | Test alerts for unavailability/deep readiness, exhausted proxy restart budget, stale started holds, ambiguous settlements, queue age, repeated failures, and volume pressure. Show the exact job/action and safe next step; no manuscript text in notifications. Route only meaningful exceptions to the operator. |
| P0 | Exercise protected release orchestration | Manual dispatch now uses a unique workflow group with cancellation disabled; ordinary CI still cancels superseded runs. Production deployments remain serialized and queued (up to 100 pending). Exercise failure/timeout and rollback/explicit resume; local configuration is not a completed production drill. |
| P1 | Extend automated post-deploy evidence | The verifier now rejects wrong/missing pipeline contracts, non-API model modes, and missing/skipped/failing Supabase or LiteLLM checks. Still add expected security-policy values and a provider-free signed-in path; header presence and public readiness alone are not complete production acceptance. |
| P1 | Recurring backup verification | Scheduled snapshots plus an independent backup and periodic isolated restore with dated evidence. Export CDN delivery alone does not preserve journals or private source artifacts. |
| P1 | Self-service support and lifecycle guidance | Contextual safe recovery and a support case containing release/job identifiers; progress/completion notifications only with appropriate consent. Account deletion, exceptional refunds, and ambiguous paid outcomes retain explicit operator ownership. |
| P1 | Measurable conversion and stop rules | Attribute campaign → signup → purchase → first complete page → export → repeat use. Join actual provider costs, credit revenue, refunds, and operator minutes. Pause acquisition on account isolation, billing, data-loss incidents, or the campaign's agreed quality/margin/support thresholds. |

The existing event allowlist still contains legacy `panel_*` names and has no
campaign/cohort attribution. Stage, checkout, purchase, and export milestones
exist, but do not yet form an acquisition measurement system. Best-effort
product events also cannot serve as the financial ledger.

## Scope and go/no-go

Stay on the existing single-Machine architecture for a bounded launch, with
measured queue limits and storage headroom. Distributed workers and object
storage are scaling work triggered by evidence, not prerequisites for learning
whether customers pay. Stage contracts, durable receipts, selected-style gating,
exact canonical lettering, and explicit paid recovery remain non-negotiable.

**Private proof:** proceed within approved accounts, source rights, and spend.
**Bounded self-service paid launch:** proceed after Gates 1–2 and all P0
operational criteria have dated evidence, the pricing/campaign plan establishes
measured caps, and support/rights/name decisions are recorded.
**Increase acquisition:** only after repeated unaided completion, acceptable
contribution margin and support burden, and the P1 automation needed for that
traffic level are demonstrated. Do not substitute a one-off founder-assisted
success for the self-service result.

## Local validation for this refresh

September 9, 2026: the targeted launch safety, deployment verifier, input-limit,
admission, credited-job, project-limit, and entrypoint suites passed **82 tests**.
The verifier now rejects non-production readiness that the previous top-level
`ok` check accepted. Workflow concurrency was also updated to protect manual
releases from superseding runs; the expression and queue behavior were checked
against official GitHub documentation and the workflow parsed locally. Documentation reliability and targeted Ruff checks passed.
These are local contract checks; no deployment, paid generation, payment, production
schema migration, or production recovery exercise was performed for this audit.
Full release CI and the deployed evidence above remain required.

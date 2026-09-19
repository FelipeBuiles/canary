# Security and billing architecture review

Reviewed: 2026-09-19. Baseline: `5eb72317b5261f46bb46594a419d83ab6c6cb965`.
Implementation: PR #13, `fix/security-billing-architecture-review`.

## Executive assessment

The pipeline already has substantial reliability machinery: typed artifacts,
explicit stage ownership, per-call usage identities, atomic credit reservation
RPCs, immutable settled usage, subscription/API funding separation, durable
request receipts, and deployment draining. Preserve these invariants rather
than replacing them with broad automatic retries or adding more server workers.

The highest-impact defects are at trust boundaries: a database-owned project row
was treated as filesystem authority; project creation accepted operator runtime
settings that the edit endpoint disallowed; checkout fulfillment depended on a
mutable catalog; and a returned refund object was treated as successful payment
settlement. This PR repairs those boundaries and adds executable regressions.

This is a source-level architecture review and targeted regression effort, not
an assertion that the deployment is secure or that an exploit has occurred.
Production database grants, customer records, Stripe configuration, infrastructure
secrets, and backup restorability were not inspected or changed. No live refund,
provider generation, database migration, or deployment was performed.

## Trust and state boundaries

| Boundary | Authority that must be preserved |
| --- | --- |
| Browser to FastAPI | Verified issuer/audience/expiry and account UUID; explicit bearer credentials for mutations. |
| Project UUID to filesystem | Owned database row AND independently validated account/project path. Ownership alone cannot authorize an arbitrary path. |
| Book settings to provider runtime | Customers choose supported book options; only the operator controls gateway addresses, credentials, mock facilities, and failed-call billing policy. |
| Stripe to credit ledger | Signature-verified payment evidence, frozen purchase terms, matching actual paid amount/currency, and unique payment identity. |
| Job admission to provider submission | Valid account reservation and durable request identity; ambiguous paid submissions must not be replayed automatically. |
| Usage to credit settlement | Immutable call identity, explicit funding source, and recorded cost evidence, not a frontend estimate. |
| Refund request to ledger reversal | Persisted eligibility/hold, stable remote identity, verified successful refund, and idempotent local completion. |

Primary implementation seams are `server/auth.py`, `server/deps.py`,
`server/admission.py`, `server/credited_job.py`, `server/credits.py`,
`server/routers/billing.py`, `server/routers/operator_billing.py`, and
`docs/supabase-schema.sql`. The web client in `web/src/api/client.ts` already
attaches the Supabase bearer token and preserves indeterminate paid-action receipts.

## Findings fixed in this PR

### High: database ownership did not constrain filesystem authority

Before this change, `get_project_dir()` and `list_projects()` joined the account
root with `projects.name` without independently validating that name. The base
schema's owner policy permitted all operations subject to table grants. An
installation with browser write grants could therefore permit an account to
change its own row into a traversal or absolute path. Subsequent API filesystem
operations would trust that owned row. An inner file-path containment check does
not help when the project root itself is wrong.

The new `project_directory()` requires single, nonhidden account/project
components and rejects account and project symlink aliases, including aliases to
another project in the same account. Project lookup fails with 404, listing skips
unsafe rows before reading metadata, and upload/import reject unsafe storage
before writing there. Account model settings reject sibling-account symlinks too.

The SQL migration revokes browser table AND column writes, retains intended
SELECT access under RLS, changes the owner policy to SELECT-only, preserves
service-role writes, and constrains new storage names. Actual production grant
state is unknown, so exposure must be assessed there; the unsafe trust chain in
the source does not depend on claiming those grants were inspected.

The filesystem check assumes the application owns the volume. It is not a
replacement for OS isolation against a hostile process racing symlink changes.

### High: project creation bypassed the runtime-settings boundary

`creation_config()` instantiated `Config(**overrides)` after rejecting only model
selection fields. That admitted gateway URLs, credentials, failed-request billing
policy, mock settings, and cloud routing fields even though the config edit API
blocked or hid them. Environment overlays can mask some settings in a particular
deployment; they should not be the security boundary.

Creation/import now reject those operator-owned fields before constructing or
persisting configuration. CLI/operator-created configurations and the existing
gated local model-selection workflow remain separate. Remote story codes are
also constrained before network access and filename construction.

Long term, use separate positive-allowlist request models for customer book
settings and operator runtime configuration instead of one broad Config model.

### High billing correctness: fulfillment used today's package definition

The original webhook looked up credit amounts in the current `CREDIT_PACKAGES`
and invented a catalog price when actual payment amount was absent or malformed.
Changing a package between checkout creation and webhook delivery could change
what a customer received. Retired or malformed paid offers could also be silently
acknowledged without fulfillment.

The server now snapshots credit count, price, currency, and receipt schema into
Checkout metadata. Only signature-verified session data is parsed. Fulfillment
requires a completed payment-mode session, matching actual paid amount/currency,
and valid Checkout/PaymentIntent identities. Unknown or contradictory paid
receipts surface a reconciliation error instead of a fabricated successful grant.

A frozen legacy catalog supports known in-flight legacy/public-credit-offer-v1
sessions. Unknown custom historical versions require operator reconciliation.
This intentionally does not use the current storefront as historical evidence.
Discounts, tax, or additional currencies require an explicit receipt-contract
change before enabling them; this version represents today's fixed USD offers.

Database payment-intent uniqueness and duplicate-safe insertion are preserved.
Both completed and asynchronous-payment-success events use that same identity.
Stripe and database failures remain retryable failures, not false success.

### High billing correctness: nonfinal refunds were completed locally

Previously, pending/requires-action refunds were not excluded from completion,
and a saved Stripe refund ID could be treated as sufficient evidence on retry.
The new path retrieves the same saved refund, checks payment identity, amount,
currency, and refund identity, and completes only when status is `succeeded`.

Pending, requires-action, failed, canceled, and unknown states retain the negative
credit hold and do not emit `refund_completed`. Existing IDs are persisted for
reconciliation rather than issuing another refund. Creation retries use the
original stored operator/amount/payment parameters and stable idempotency key.
Local persistence or settlement failures preserve an explicit recovery path.

This does not retroactively correct old rows already marked completed. Historical
records must be compared with Stripe before an operator adjusts anything.
Failed or abandoned refunds can retain holds until manual reconciliation; that
is conservative financial behavior, not a complete automated refund lifecycle.

### Medium: incomplete JWT/cookie policy and blocking network verification

Signature validation existed already; this was not an unsigned-token bypass.
The verifier now requires expiry, issuer, and subject claims; checks the configured
Supabase issuer; and normalizes a UUID subject. Production cannot disable audience
validation with an empty override or disable Secure cookies with a false flag.
Malformed explicit authorization never falls back to a cookie.

HttpOnly cookie access remains available to native image/download/EventSource
reads. Mutating HTTP methods require bearer authentication, matching the existing
web API client. This reduces dependence on SameSite cookies as a CSRF boundary;
it does not claim that every existing GET handler is free of internal repair
side effects or that XSS has been eliminated.

JWKS network verification and Stripe checkout/webhook database work run outside
the API event loop. Other synchronous paths still merit latency profiling.

## Prioritized architecture follow-ups (not implemented here)

### P1: make payment reconciliation a durable subsystem

Checkout webhooks plus an operator refund endpoint are not a complete payment
lifecycle. Add an append-only webhook inbox with unique event IDs, an explicit
payment/refund/dispute state machine, and a reconciliation view/worker. First
produce auditable discrepancies and operator actions; do not automatically
reissue refunds or reverse already-spent credits without an agreed policy.

Acceptance cases: duplicated/out-of-order events; successful payment with no
credit grant; refund pending then failed; success followed by local response loss;
chargeback after credits were consumed; deleted accounts with retained financial
records; and historical incorrectly completed refunds. Analytics should come
from a transactional outbox so a crash after ledger commit cannot lose the
business event. The ledger, not analytics, remains the financial authority.

Relevant seams: billing/refund routers, `product_events.py`, and the SQL ledger.

### P1: freeze job billing terms and authorize incremental spend

A stage estimate and a reservation lease do not, by themselves, prove a hard
maximum on a multi-call provider sequence. Define a server-enforced cumulative
budget, extend reservations atomically before additional paid work, and stop
before the next submission when funds or the chosen budget are exhausted.
Already submitted ambiguous calls must retain evidence and their liability.

Review settlement across restarts/configuration changes as well. The cumulative
job settlement RPC receives conversion/markup parameters on each call; freeze a
job's billing-policy version and conversion terms rather than allowing later
configuration to reprice prior accumulated provider cost. Validate finite,
positive operator pricing parameters at startup and expose the active version
in reconciliation. No claim is made here about the deployed markup value.

Acceptance cases: an underestimated multi-call job, two projects competing for
remaining funds, operator rate changes during a job, fractional-credit rounding,
provider cost exceeding estimate, and crash after provider success but before
local settlement. Preserve immutable usage-call identities and subscription
funding separation while adding these controls.

### P1 before scaling: make the execution model explicit

Local request journals, filesystem artifacts, process locks, queues, and lease
ownership are coherent under the current single-writer deployment assumptions.
Adding Uvicorn workers or multiple Machines is not a safe scaling switch.

Before that change, design shared durable job claims, fenced ownership, atomic
artifact publication, per-account/project concurrency, and recovery semantics
for each provider submission state. Prove that two workers cannot dispatch one
paid intent twice. Test volume backups and restoration of both artifacts and
request/payment evidence. Retain deployment draining during the transition.

Relevant seams: `admission.py`, `generation_jobs.py`, `credited_job.py`,
`app.py`, and deployment status/draining code.

### P2: transactional quotas and declarative route policy

Project creation counts existing rows and later inserts a new row. Concurrent
creations with different names can exceed a count-based quota. Browser-write
revocation closes a separate bypass but does not serialize this API race. Reserve
project slots atomically and account for bytes and orphaned staging directories.

Keep paid-action and mutation policy next to route declarations, with an exhaustive
contract test for every mutating route. A separately maintained route-matching
inventory can drift as new generation/recovery endpoints are introduced. This is
a maintenance risk, not an assertion that every recovery endpoint is unguarded.

### P2: unify export identity and freshness checks

`server/routers/export.py` keys export locks using a project directory's basename.
Accounts can share that basename, causing unnecessary cross-account contention.
Use the composite account/project identity. This is an availability/isolation
issue, not demonstrated cross-account file disclosure.

Preflight, cached export return, and download should all enforce the same
artifact-version/currentness contract. Centralize a verified manifest gate and
test edits after export, stale validator versions, and missing/corrupted files.
An existing export file is not, on its own, proof that it represents the current
approved edition. Recovery must not silently regenerate paid artwork.

### P2: constrain resource retention without destroying idempotency

Profile synchronous database/filesystem work still reached from async handlers.
Use bounded worker execution or supported async clients where measurement shows
blocking, rather than unbounded thread offloading. Define retention for completed
request receipts and per-project in-memory state, but retain compact paid-action
tombstones and unresolved evidence so cleanup cannot turn retries into new charges.

## Rollout and verification

Apply `docs/sql/2026-09-19-project-trust-boundary.sql` as the database owner on
existing installations AND after `docs/supabase-schema.sql` on new installations.
The base schema alone is not the new authorization contract. The migration is
replayable and uses a NOT VALID storage-name constraint so legacy bad rows cannot
prevent privilege revocation. New/updated rows are constrained immediately.
Audit the supplied query's results, repair ownership/storage mappings deliberately,
then validate the constraint. Do not blindly rename/delete a suspicious target.

Confirm that external integrations do not depend on direct browser project
writes. Smoke-test sign-in/token refresh, project creation/import/list/delete,
account model settings, native authenticated images/downloads, and Stripe test-mode
checkout/refund scenarios. Audit historical refunds and unknown legacy offers;
this code intentionally does not manufacture evidence for them.

Regression coverage includes signed-token failures, cookie mutation rejection,
path traversal and symlink aliases, actual route/helper boundaries, malformed and
historical purchase receipts, duplicate fulfillment, refund-state transitions,
response-loss recovery, browser table/column grants, RLS visibility, RPC execution
permissions, and real concurrent PostgreSQL credit reservations. The new isolated
CI job applies the base schema and migration twice and runs the actual ledger
contracts rather than silently skipping them without a database.

Code commit `4e94d5c` passed 103 focused API/security tests and 17 real
PostgreSQL tests in GitHub Actions (run `35454905923`), including migration replay.
The local source harness also passed its 87 external-service-double tests.
Broader regression results and unrelated baseline CI failures are recorded in
PR #13. Neither passing mocks nor an isolated PostgreSQL fixture certifies the
live Supabase/Stripe configuration.

Primary external contract references: Supabase's API security documentation
(grants plus RLS), PyJWT's API/usage documentation (required claims versus claim
verification), and Stripe's refund documentation (nonfinal refund states and
refund lifecycle events).

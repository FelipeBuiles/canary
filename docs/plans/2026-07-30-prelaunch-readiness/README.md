# Scenewright — pre-launch readiness execution plan

**Date:** 2026-07-30
**Status:** Superseded September 9, 2026 by the
[self-service launch strategy](../../proposals/self-service-launch.md).
Retained as historical sequencing and evidence requirements; operator-led
onboarding and old page-count hypotheses are not the current launch motion.
**Decision target:** a small paid, operator-assisted design-partner pilot,
followed by a measured public launch if the evidence supports it.

This is the execution companion to
[the market and launch-readiness reassessment](../../research/2026-07-30-market-and-launch-readiness.md).
It brings back the durable operating structure from the deleted Slice 0 and
Slices 1–7 documents without restoring their panel-era stage contracts.

## Operating decision

Scenewright is **not ready for a public launch today**. The next authorized
step is a production proof run and, only after its gates pass, a cohort of no
more than two paid authors at a time.

The first offer is a learning instrument:

- the customer buys credits, not a guaranteed page count;
- a 6–12 complete-page excerpt is a planning hypothesis, not a promise;
- the workflow uses one approved look/cast direction and the current
  Extract → Brief → Look → Pages → Book flow;
- complete pages, visible lettering, page issues, corrections, and PDF/CBZ
  export are part of the proof;
- customer work is never used in public marketing without written consent.

## Scope and non-goals

In scope:

- release identity and exact-SHA deployment;
- production auth, data isolation, billing, monitoring, recovery, backup, and
  support;
- provider-backed complete-page and lettering acceptance;
- measured credit economics and a truthful first-value path;
- name/rights/support decisions;
- a small operator-assisted cohort and permissioned proof.

Not in scope for this plan:

- restoring the old panel, storyboard, direct, or compose pipeline;
- a compatibility layer for deleted stage names or artifacts;
- broad paid acquisition before the cohort produces evidence;
- a public page-count or per-book price promise;
- a new analytics platform before a small first-party source/cohort record is
  sufficient.

## Readiness slices

### Slice 0 — offer, name, and ownership decision

Before customer-facing activity, record:

- public trial versus purchase-first access;
- Starter package language and what it does not guarantee;
- Scenewrite/SceneWrite name decision or rename;
- support, billing, legal, recovery, and proof owners;
- manuscript/reference rights acknowledgement and AI disclosure;
- retention, deletion, refund, abuse, and case-study consent policy.

Exit evidence:

- [ ] written offer decision;
- [ ] written name decision or rename ticket;
- [ ] named operators and monitored contact routes;
- [ ] customer-facing rights/AI/refund language reviewed.

### Slice 1 — clean release candidate

Reconcile the current full-page branch and user-owned working-tree changes,
then run the same source revision through:

- backend tests and Ruff;
- web tests, lint, and production build;
- production dependency and container checks;
- the full-page contract gates;
- deployment safety/version checks.

Exit evidence:

- [ ] source SHA and branch recorded;
- [ ] exact-SHA CI run is green;
- [ ] release evidence record is filled;
- [ ] rollback target and deploy operator are recorded.

The blank template is
[docs/ops/release-evidence-template.md](../../ops/release-evidence-template.md).

### Slice 2 — deployed safety and operations

Against the deployed SHA, verify:

- Supabase schema, RLS, service-role boundaries, and two-user isolation;
- signup, login, reset email, project creation, uploads, and deletion;
- Stripe paid Checkout, duplicate webhook, unpaid webhook, refund, and
  insufficient-credit recovery;
- readiness, security headers, trusted host/app URL, and TLS;
- Sentry event/alert, application logs/metrics, and operator escalation;
- mid-generation interruption/recovery;
- backup snapshot restore and recovered PDF/CBZ export;
- support response, abuse/DMCA, deletion, and billing runbooks.

Exit evidence:

- [ ] deployed acceptance record with timestamps and operator;
- [ ] no cross-user data or credit exposure;
- [ ] no unreconciled reservation/refund;
- [ ] at least one restore and one interrupted generation recovered;
- [ ] monitored support and incident contacts verified.

Use [the deployment runbook](../../deploy.md) and the runbooks in
[docs/ops](../../ops/).

### Slice 3 — complete-page visual proof

Use a public-domain or explicitly licensed source and an explicitly authorized
provider budget. Run the deployed product through the complete path:

Extract → Brief approval → Style → Cast approval → Adapt → Plan → Draw →
page issue review/correction → Finish → PDF/CBZ.

Record for every page:

- page and render revision;
- page/request/image hashes and provenance;
- provider/model profile and reference count;
- visible lettering expected versus OCR-observed;
- open/resolved/accepted page issues;
- correction attempts and retries;
- credits estimated, held, settled, and released;
- provider cost, elapsed time, operator minutes, and export result.

Exit evidence:

- [ ] minimum pilot scope of 6–12 complete pages is affordable and repeatable;
- [ ] recurring characters and locations are reviewed across the sample;
- [ ] lettering is readable and exact enough for the agreed threshold;
- [ ] correction behavior works without creating panel ownership;
- [ ] PDF and CBZ open and contain the expected pages;
- [ ] all failures have an operator recovery path.

Do not reuse the old 30–50-panel benchmark as if it were equivalent. A larger
complete-page benchmark may be useful later, but only after the initial
measurement and budget decision.

### Slice 4 — economics and offer calibration

Replace the panel-era pricing assumptions with actuals from Slice 3. Include:

- upstream text/style/cast cost;
- complete-page base generation;
- reference inputs;
- OCR/render analysis;
- retries and corrections;
- failed-call billing behavior;
- storage/compute/provider overhead;
- Stripe fees, refunds, support time, and operator time;
- settled credits versus reserved credits.

Exit evidence:

- [ ] Starter and Standard coverage guidance recalculated;
- [ ] contribution-margin threshold agreed;
- [ ] support-minute threshold agreed;
- [ ] page-count examples removed if they are not supported;
- [ ] public pricing and estimate language updated.

The current code package table remains a product input. The old book coverage
and margin model in
[pricing-and-margin.md](../../proposals/pricing-and-margin.md) is not launch
evidence.

### Slice 5 — two-author learning cohort

If Slices 0–4 pass:

1. admit two authors, one at a time if support requires it;
2. keep the operator in the loop for upload, approvals, corrections, and
   export;
3. record source, paid start, first completed page, export, repeat intent,
   support burden, satisfaction, and proof consent;
4. publish nothing without permission;
5. stop immediately for data isolation, billing, loss, rights, or unresolved
   quality failures.

Exit evidence:

- [ ] two independent authors complete the agreed path or a documented reason
  for stopping exists;
- [ ] at least one customer permits a case study or the reason for no proof is
  recorded;
- [ ] successful export and support burden meet the thresholds;
- [ ] the offer is revised from observed behavior.

### Slice 6 — public launch authorization

Public launch requires a written decision that all of the following are true:

- [ ] exact-SHA release and rollback are repeatable;
- [ ] live billing and credit reconciliation are monitored;
- [ ] auth, isolation, readiness, recovery, backup, and support are exercised;
- [ ] full-page quality and lettering thresholds are met;
- [ ] unit economics and support burden are acceptable;
- [ ] first value is truthful at zero balance or the product is explicitly
  purchase-first;
- [ ] name risk has a written resolution;
- [ ] customer-owned proof is permissioned;
- [ ] source attribution/cohort reporting is working;
- [ ] current product docs no longer direct operators to panel-era behavior.

## Evidence package

The launch packet should be small enough to inspect:

1. release evidence record;
2. deployed safety acceptance record;
3. full-page visual/economics worksheet;
4. offer, name, rights, and support decisions;
5. pilot cohort notes and consent records;
6. final public copy/FAQ/pricing review.

No item is complete because code exists. Each item needs a dated result,
operator, environment, and link to the artifact or dashboard evidence.

## Stop conditions

Stop the pilot and return to the relevant slice for any:

- cross-user project, asset, or credit visibility;
- paid/unpaid/refund mismatch;
- lost page, missing lettering, or unrecoverable export;
- unmonitored production failure;
- unsupported rights or name claim;
- provider cost or support burden outside the agreed threshold;
- customer work used without consent.

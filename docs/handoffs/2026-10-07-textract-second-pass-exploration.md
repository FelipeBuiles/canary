# Textract second-pass OCR exploration handoff

**Status: Proposed exploration, October 7, 2026 (America/Toronto).** Repository
and pricing observations below are a dated snapshot. No Textract image calls,
implementation, credit-eligibility verification, or production activation have
been completed by this investigation.

## Objective and scope

Determine whether AWS Textract is worth implementing as Canary's optional,
blind second read of disputed comic lettering. Deliver a concrete architecture,
an engineering-effort estimate, a recurring-cost model, and an account-specific
answer about whether our AWS promotional credits cover its usage.

The user requested this handoff for exploration. Start with code, existing
hardware evidence, official documentation, and read-only AWS account inspection.
An offline prototype can make the estimate concrete. Prepare a bounded live
pilot proposal; this handoff alone does not authorize paid OCR submissions,
deployment, billing/IAM changes, or production enablement. Work in the shared
checkout, preserve other edits, and leave development servers to the user.

## Evidence to reuse

- [Lightsail benchmark](../reviews/2026-10-07-ocr-lightsail-benchmark.md):
  production uses a 2-vCPU, 4-GB Lightsail instance in `us-east-1`. At the
  simulated sustainable 0.4-vCPU entitlement, Paddle took 36.81 seconds for the
  first crop and a median 10.89 seconds for a warm crop. Concurrent/multi-crop
  checks exceeded their budgets. There were no measured OOM events; this was
  chiefly a throughput/contention failure, alongside native-runtime issues.
  Three successful English caption reads do not establish general accuracy.
- [Crop experiment contract](../reference/crop-ocr-experiment.md): disabled by
  default; tight crops of saved base art; pixels only, without canonical text or
  the first transcription. Integrated and retained baked editions participate;
  hybrid editions retain their separate unwanted-lettering check. Maximum six
  crops per page, 3 million pixels per crop, 24 million pixels per source page,
  and a 30-second page read budget.
- [Stage contracts](../reference/stage-contracts.md): OCR is advisory evidence.
  Conflicting/weak reads never certify copy, resolve author decisions, or verify
  a visual concern. No new pipeline stage or artwork generation is needed.
- [Deployment](../deploy.md), [secret delivery](../ops/secret-delivery.md), and
  [job queue](../reference/job-queue.md): one artifact-volume owner, existing
  durable execution/accounting, and explicit process credential scopes.

### Verified Textract pricing

On October 7, the AWS connector successfully queried `Pricing.GetProducts` for
service code `AmazonTextract`, usage type `USE1-SyncTextPagesProcessed`. Product
SKU `MU9BPN7BUTB9FTQJ`, published September 11, 2026, reports synchronous
`DetectDocumentText` in N. Virginia at **US$0.0015 per submitted image/page for
the first million each month**, then **US$0.0006 for additional pages**.
Recheck at execution time. [AWS pricing](https://aws.amazon.com/textract/pricing/)
and [Price List Query API](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/using-price-list-query-api.html).

Each separately submitted crop is one billable image. A smaller crop has the
same unit price as a full-page image. The following calculations assume all
requests remain in the first pricing tier and exclude first-pass OCR, retries,
taxes, and any relay infrastructure:

| Pages requiring second-pass checks | One crop each | Six crops each |
| --- | ---: | ---: |
| 100 | $0.15 | $0.90 |
| 1,000 | $1.50 | $9.00 |
| 10,000 | $15.00 | $90.00 |
| 100,000 | $150.00 | $900.00 |

A 100-crop accuracy pilot costs $0.15 before offsets. A 100-page book with 20%
of pages disputed and two crops per disputed page costs $0.06 for this pass.
These are calculated scenarios, not observed usage or net cash charges.

### Existing credit evidence: eligibility remains unknown

The [October 6 migration investigation](../proposals/aws-lightsail-migration.md#evidence-and-credit-status)
recorded `FreeTier.GetAccountPlanState` as `PAID / ACTIVE` with **$199.98**
remaining. That is historical balance evidence, not today's balance or proof
that Textract is eligible. `Billing.GetCredits` was denied with **"IAM user
access not activated."** No permissions were changed.

The user supplied an expiry displayed as `10/02/2027`; its month/day interpretation
was not resolved. Do not convert this into an assumed October expiry. Identify
the actual grant rather than assuming an Activate grant, a Free Tier allowance,
or eligibility merely because Lightsail is covered.

## Architecture exploration

Begin with these implementation locations; names and boundaries should be
rechecked against the current checkout:

- `novel_to_comic/src/novel_to_comic/crop_ocr.py`: `CropReader.read`,
  `reader_from_environment`, `verify_mismatches`, cache identity and verdicts.
- `novel_to_comic/src/novel_to_comic/models/crop_ocr.py`: typed line/read/report
  artifacts, pixel bounds, confidence, completeness, and physical-line assembly.
- `novel_to_comic/src/novel_to_comic/page_review.py`: `analyze_page_render`,
  `revalidate_cached_page_render`, and `_validate_observations`.
- `novel_to_comic/src/novel_to_comic/server/routers/pages.py`: text-check
  estimate, cached-evidence recovery, `allow_paid`, and explicit analysis routes.
- `novel_to_comic/src/novel_to_comic/server/credited_job.py`,
  `server/page_operations.py`, `server/operations.py`, and `ai/client.py`:
  existing authorization, usage settlement, attempt and recovery authorities.
- `scripts/canary_secrets.py`, `litellm/entrypoint.sh`, and
  `novel_to_comic/pyproject.toml`: credential delivery/process scope and SDK
  dependency changes. The application currently has no `boto3` dependency.
- `novel_to_comic/tests/test_crop_ocr.py`, `scripts/ocr_crop_experiment.py`, and
  `scripts/ocr_crop_benchmark.py`: existing provider-free contracts and fixtures.

Compare a small number of viable designs:

| Design | Questions the exploration must settle |
| --- | --- |
| Direct Textract SDK from the existing analysis/job process | Smallest transport change? Where do Textract credentials live, and how are attempts, usage, deadlines, and recovery recorded? |
| Textract adapter behind the existing gateway | Can this reuse existing provider credential isolation and accounting without forcing Textract blocks into an incompatible chat/OCR schema? What extra custom handler is needed? |
| Minimal AWS relay, such as Lambda with a service role | Does avoiding AWS credentials in the application justify another authenticated endpoint, deployment, receipt store, and Lambda/logging cost? |

Favor reuse of existing job, artifact, and accounting authorities. Do not add a
second worker owning the project volume or move the application to EC2 solely
for this experiment. Confirm Lightsail's supported credential options rather
than assuming an EC2 instance profile is available. The current secret bundle
rejects AWS access-key tuples; its existing `AWS_BEARER_TOKEN_BEDROCK` is not a
Textract credential solution. Any selected credential path needs an explicit,
scoped design and identified secret-delivery changes.

The initial transport candidate is synchronous `DetectDocumentText` with PNG
crop bytes. It supplies lines/words, bounding geometry, confidence, and a
response model version; an S3/SNS asynchronous pipeline is unnecessary for
ordinary single crops. [Detection API](https://docs.aws.amazon.com/textract/latest/APIReference/API_DetectDocumentText.html).
Compare independent crops with one full-page request only as an experiment:
full pages reduce request count but change isolation, detection, and grouping.
Do not claim equal quality without testing.

Resolve these integration details before calling an adapter production-ready:

1. **Paid work versus cached validation.** Today `revalidate_cached_page_render`
   is documented as provider-free, yet it can invoke the local crop reader.
   Cached recovery can run before paid-call admission/settlement. A naive SDK
   substitution could spend inside a path considered free, including when
   `allow_paid=False`. Keep cache/status reads local and schedule/admit hosted
   reads explicitly. Current page-list GETs read evidence/status; do not claim
   they already run paid OCR.
2. **Durable attempts and recovery.** Preserve each submitted crop, response,
   request ID, model version, image hash, billed-unit estimate, and outcome.
   Current incomplete crop reports are not persisted and local revalidation can
   repeat them; this cannot be inherited unchanged for paid reads. Retain
   successful partial responses, prevent duplicate concurrent submissions, and
   make timeout/unknown-outcome handling explicit. A request hash is not provider
   idempotency. Specify SDK retry behavior and avoid an unbounded resubmission
   loop.
3. **Evidence conversion.** Convert normalized Textract geometry into submitted
   crop pixel bounds and confidence from 0–100 into the 0–1 schema. Evaluate
   conservative word-level confidence for a line. Do not inherit Paddle's
   uncalibrated 0.95 threshold as established Textract accuracy. Keep provider,
   region, response model version, preprocessing, policy and exact lineage in
   provenance/cache design; the hosted model cannot be fingerprinted like local
   model files. [Block schema](https://docs.aws.amazon.com/textract/latest/APIReference/API_Block.html).
4. **Bounds and concurrency.** Keep a total page deadline covering local
   preparation, admission, HTTP calls and backoff. Distinguish TPS pacing from
   in-flight concurrency and queue wait. The documented default in `us-east-1`
   is 25 synchronous detection starts/second, not guaranteed latency or our
   verified account quota. [Quotas](https://docs.aws.amazon.com/general/latest/gr/textract.html).
   Cropping/encoding still consumes local CPU/RAM, especially with concurrent
   24-million-pixel source pages. AWS documentation differs between a 10-MB
   synchronous quota and 5-MB wording in the image-bytes reference; use a
   conservative byte cap for the pilot and resolve the supported production
   limit. [Input limits](https://docs.aws.amazon.com/textract/latest/dg/limits-document.html),
   [Document input](https://docs.aws.amazon.com/textract/latest/APIReference/API_Document.html).
5. **Accounting and author experience.** Identify whether Canary absorbs this
   incremental review cost or includes it in author estimates. Keep list-price
   provider cost, uncertain submission cost, promotional offsets, and charged
   Canary credits distinct; offsets do not make provider usage zero. Preserve
   existing advisory findings, author decisions, and hybrid exclusions.

Return a preferred design with file-level changes, one small flow diagram if
useful, and separate estimates for the offline adapter, live evaluation,
production integration, credential/infrastructure setup, and verification.
Use engineering-day ranges with assumptions and dependencies, rather than an
unsupported single total. Identify the minimum useful first implementation.

## Verify promotional-credit coverage

Public [promotional-credit terms](https://aws.amazon.com/awscredits/) restrict
coverage to designated eligible services. Textract being an AWS service is not
account-specific proof. Verify the actual grant and usage account.

1. Resolve the connected account with `STS.GetCallerIdentity`, and identify
   which account would submit Textract requests. Avoid committing full account
   IDs or private billing exports into this repository.
2. Use read-only `Billing.GetCredits` if available. Its documented request uses
   `accountId`, a past `startDate` within the preceding year, and optional
   `endDate`/`payerAccountFlag`. Obtain current time first and choose a sufficient
   lookback; do not use a future billing end date. Record all returned grants
   relevant to the submitting account. [GetCredits API](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_billing_GetCredits.html).
3. Capture each grant's name/type, enabled status, effective dates, remaining
   balance, estimated balance, applicable products, purchase-type restrictions,
   and any account-sharing scope. `estimatedAmount` includes open bills;
   distinguish it from `remainingAmount`. Resolve the exact Textract product
   entry and the grant's `endDate` into an unambiguous ISO date. Missing product
   information is unknown, not permission to assume universal eligibility.
   [Credit data fields](https://docs.aws.amazon.com/aws-cost-management/latest/APIReference/API_billing_CreditData.html).
4. If the same IAM billing denial remains, use an already-authorized read-only
   [Billing → Credits](https://console.aws.amazon.com/billing/home#/credits)
   session and inspect the actual grant's complete applicable-products list.
   Do not enable IAM billing access or change policies as part of the audit.
   If neither route is accessible, report the exact access limitation and the
   missing grant facts needed from the owner.
5. Check other services introduced by the preferred architecture independently
   (for example Lambda, logging, S3, or a request endpoint). Separate grant
   eligibility from remaining funds after Lightsail and other usage consume
   the same balance. AWS applies eligible credits during billing; reported
   balances/allocations can update on different schedules. [Credit application
   and console evidence](https://docs.aws.amazon.com/awsaccountbilling/latest/aboutv2/useconsolidatedbilling-credits.html).
6. If an approved pilot later produces charges, inspect credit allocation or
   the bill after usage appears. Distinguish **eligibility confirmed** from
   **actual offset observed**. A zero bill could reflect a service free tier;
   a pending credit entry does not by itself prove ineligibility. Do not run a
   charge solely to test billing without a bounded pilot authorization.

The report must conclude **covered**, **not covered**, or **unverified**, with
dated account/grant evidence and applicable conditions. A balance lookup,
generic Activate FAQ, or eligibility for a different service is insufficient.
Use scripts with decimal arithmetic for cost/balance calculations. Do not
change account plans, credit-sharing preferences, or AWS Organizations.

## Evaluation and cost model to prepare

Prepare a human-labelled set of about 100 independent saved lettering crops:
known first-pass false alarms, genuine rendered errors, correct controls, small
type, difficult names/punctuation, multiple balloons, decorative text and the
intended output languages. The recognizer receives only image pixels. Reuse the
three original fixtures as regression controls, not the entire accuracy sample.

Textract documents six printed-text languages, English-only handwriting,
15-pixel minimum character height, and no vertical-text support. Check whether
that covers intended editions. [Supported inputs](https://docs.aws.amazon.com/textract/latest/dg/limits-document.html).
Synchronous detection is described as near real time; no Canary Textract
accuracy, median latency, or p95 latency has yet been measured. [Processing
model](https://docs.aws.amazon.com/textract/latest/dg/sync.html).

Propose a request-count and USD cap before any live test. **100 requests / $0.15**
is an accuracy-only starting point at the verified rate; contention tests,
crop-versus-full-page comparisons, or repeated measurements require additional
requests and a separately calculated total. A cache hit is not a fresh latency
sample. Provider-free tests should verify conversion, isolation, cache behavior,
partial persistence, deadline handling, and absence of spend on free recovery.

For a subsequently authorized live evaluation, measure issue precision,
real-error recall, inconclusive rate, human review burden, crop and whole-page
latency, queue time, retries/throttling, local resource use, and submitted units.
Compare 1/4/16 concurrent pages with one/six disputed crops against the current
30-second budget. Preserve failures as failures and distinguish completed checks
from partial reports whose status happens to say `disagrees`.

Calculate recurring usage as generated pages × disputed-page fraction × average
crops per disputed page, plus explicitly modeled repeat attempts. Cover low,
expected and high workloads, optional infrastructure, gross AWS cost, estimated
promo-covered cash cost, and cost after credit expiry/exhaustion. Show engineering
effort separately from service fees; credits do not offset engineering time.

## Completion criteria

Deliver a dated exploration report containing:

- The preferred architecture, alternatives rejected with reasons, concrete
  implementation boundaries, and engineering-effort ranges.
- An account-specific promotional-credit verdict with evidence, or a precise
  unresolved access/eligibility question; preserve the historical denial.
- Reproducible gross and net cost scenarios and a separately costed pilot plan.
- A quality/latency evaluation plan, distinguishing documented capability from
  measured comic results. Include actual results only if live work was authorized.
- The recommended next slice and any remaining decision that materially changes
  scope, correctness, funding, or deployment.

For documentation changes, run `python3 scripts/check_docs_reliability.py`.
If a provider-free prototype is added, run the affected focused backend tests
and Ruff; broaden only when shared contracts change. Do not treat mocked tests
as comic-quality evidence or start/restart servers for exploration.

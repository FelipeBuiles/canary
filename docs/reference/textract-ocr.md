# Textract close-up OCR

**Status: Implemented; local live pilot passed, October 7, 2026.** Provider-free
tests cover transport, evidence cache, recovery and funding contracts. Three
English crops were read correctly through an isolated gateway in 2.1–3.3 seconds;
the repeated run reused all receipts in 2–3 ms with zero new requests. Production
activation is pending the release checks and secret-loader rotation.

## Behavior

Set `CANARY_TEXTRACT_ENABLED=true` in the application process to add a blind
second read of disputed integrated/baked lettering during an admitted page
check. The default is false. When enabled this replaces the local Paddle
experiment; hybrid unwanted-lettering checks keep their existing behavior.
The author sees one plain-language conclusion per difference (read the same
way twice, a closer look matches the script, or hard to read/not yet
double-checked); the raw reads stay behind the full-comparison disclosure. Canary absorbs the fee; first-pass OCR retains its
existing funding rules.

Only cropped PNG pixels reach the gateway's internal `ocr-textract` route.
Canonical copy, first-pass text, prompts and suggested corrections are excluded.
Textract `DetectDocumentText` receives bytes directly, without S3 or asynchronous
jobs. The saved raw answer retains LINE/WORD blocks, confidence, geometry,
request ID and model version. Comparison happens locally afterward.

The converter requires complete LINE/WORD evidence and valid geometry. It uses
the minimum line/word confidence with a provisional 0.80 threshold; this is
not a calibrated accuracy claim. The gate is deliberately below the pilot's
correct ~84% reads because a conclusion also requires the blind read to equal
the first read or the script. Lines joined at a hyphenated wrap are compared as
one word and as a kept compound. Overlapping adjacent lines remain inconclusive.
Disagreement or low confidence cannot certify artwork, rewrite canonical copy,
resolve visual concerns, or reset author dismissals. Missing regions and
oversized crops stay inconclusive.

## Bounded work and recovery

- One source image is decoded at a time across pages; source ceiling 24 MP.
- At most six tight crops per page, each at most 3 MP, 10,000 pixels per side,
  and 4 MB encoded PNG. No upscaling or full-page fallback.
- Thirty-second page admission/submission budget, including crop preparation
  and queueing. A running SDK call may finish after the caller times out;
  its slot remains occupied until it exits. No new submission starts after
  the deadline. Native image work cannot be forcibly interrupted mid-operation.
- The single gateway process admits at most four concurrent SDK calls and
  smooths starts to five per second. Keep a single gateway worker; these are
  process-local limits, not an account-wide distributed limiter.
- No SDK retries, application repair loop or provider fallback. Each crop
  attempt is written atomically before submission. Identical pixels in the
  same render reuse successful recognition even after validator changes.
  Enabling the reader or retuning its threshold does not change the Draw
  validator version, so saved page checks stay current; new interpretation
  applies when a page is next checked.
- Crashes/timeouts leave an explicit unknown outcome. Automatic Draw recovery,
  GETs and free recovery never resubmit it. An unfinished second look leaves
  the page checked; the finding's free Double-check action
  (`second_look_only`) can retry missing/failed/unknown work after an active
  attempt's deadline; successful crops are retained. A lost response may
  still incur AWS cost. Unreachable-gateway and gateway 4xx refusals (except
  408) are known failures, and a usage-projection failure never blocks or
  reclassifies submission.

`TargetArtifacts` stores plans, cropped bytes and attempts under the render's
analysis directory. The plan records source hash, bounds and dimensions;
recognition identity includes source/crop hashes, preprocessing, model and
region. Provider evidence is separate from canonical comparison. The cache is
scoped to the part and render, not shared between authors. Crops and OCR text
inherit the project's existing private storage and retention behavior.

A raw successful receipt is saved before SQL usage projection. It is the durable
authority if optional telemetry/database writes fail. An unknown receipt has no
asserted actual cost; its one-image estimate remains available for reconciliation.
The application does not recover provider responses lost after HTTP cancellation.

## Credentials and activation

Supply these **gateway-only** secrets through the existing encrypted bundle:
`CANARY_TEXTRACT_ACCESS_KEY_ID`, `CANARY_TEXTRACT_SECRET_ACCESS_KEY`, and optionally
`CANARY_TEXTRACT_SESSION_TOKEN`. The loader requires a complete pair and the
entrypoint removes all three from the web child. Do not put generic AWS keys
in the production secret bundle. Local Compose also forwards the named keys;
`CANARY_TEXTRACT_AWS_PROFILE` is an explicit local alternative using the existing
AWS-login credential mount. Generic Bedrock credentials are never a fallback.

The intended IAM grant is only `textract:DetectDocumentText` with `Resource: "*"`
and `aws:RequestedRegion` constrained to `us-east-1`. Credential provisioning,
rotation, deployment and server refresh remain operator actions. Changes to the
secret loader require updating its pinned digest through the existing
[secret-delivery procedure](../ops/secret-delivery.md).

The model alias, region and interpretation threshold live in application
configuration; the unit price lives in `litellm_pricing_overrides.yaml`.
Successful crop reads record one document page and US$0.0015 gross provider
cost under the first-million-page tier, with pricing snapshot and zero author
credits. Tier discounts and promotional-credit allocation are reconciled with
AWS billing separately. No image tokens or invented token usage are charged.

On October 7 the user confirmed promotional credits cover Textract and approved
Canary absorbing its fee. Grant expiry and actual credit allocation were not
independently verified. The earlier [exploration](../proposals/textract-second-pass-ocr.md)
records the original account-access limitations and proposed 100-request,
US$0.15 gross-cost pilot. The local pilot used the reported English caption and two spelling controls.
The caption produced a decisive disagreement at 99.96% minimum confidence; both
synthetic controls were transcribed correctly but remained inconclusive at
about 84% confidence. All three receipts succeeded, recorded zero author credits,
and totaled US$0.0045 gross before promotional credits. Matching first-pass copy
skipped the worker. These samples establish this specific regression and safe
cache behavior, not broad language accuracy. Expand labeled English, Spanish
and French evidence to measure false confidence, inconclusive rate and unknown
outcomes. No real-image quality claim follows from mocked tests.

## Verification entry points

`scripts/textract_crop_pilot.py` accepts the labeled manifest used by the local
crop experiment and writes isolated evidence under `--output`. Without
`--allow-paid` it only prepares crops and reports a request upper bound. Paid
runs enforce `--max-requests` (default 10, maximum 100), reuse saved receipts,
and never retry unknown outcomes. Set `LITELLM_BASE_URL` and `LITELLM_API_KEY`
privately for the test gateway; do not put credentials in command arguments.

```sh
novel_to_comic/.venv/bin/python scripts/textract_crop_pilot.py \
  --manifest work/textract-pilot/manifest.json \
  --output work/textract-pilot/run-1 --max-requests 10
# Add --allow-paid only for an approved live run.
```

Production Compose exposes `CANARY_TEXTRACT_ENABLED` with a false default.
The checked-in [runtime policy](../../deploy/iam/textract-detect-text.json)
is restricted to text detection in the configured region.

- `novel_to_comic/tests/test_textract_ocr.py`: persisted attempts, free recovery,
  cache reuse, conservative evidence, pixels-only HTTP payload and funding.
- `litellm/tests/test_textract_contracts.py`: pinned LiteLLM custom-provider
  serialization, scoped boto3 configuration, deadlines and cancellation slots.
- Existing page recovery, crop OCR, usage, secret-delivery and entrypoint tests
  cover the surrounding contracts. Frontend lettering evidence tests cover
  unfinished and interrupted-check guidance in the existing card.

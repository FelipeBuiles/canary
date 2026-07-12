# Slice 15 Visual Evaluation Proposal and Report

Date: 2026-07-12

Status: **CURRENT-PIPELINE ABSOLUTE BENCHMARK COMPLETE — FULL STATE/PAIRED ACCEPTANCE PENDING**

Authorization was received on 2026-07-12 for the proposed 16 image calls and
32 evaluator calls within the stated 36–74 credit planning range. The initial
shell preflight found no historical retained baselines and could not
authenticate directly to the provider gateway. The user therefore approved
reframing the work as an absolute current-pipeline benchmark and launched it
through the authenticated app. It does not support an old-versus-new compiler
improvement claim.

### Current-pipeline benchmark attempt

The user subsequently authorized an absolute current-pipeline benchmark using
only production `image-balanced` and launched the app's eight-panel default
fixture as run `f61c740a049d`. All eight gateway requests returned HTTP 200, but
Canary failed to decode the results with `[Errno 20] Not a directory: 'var'`.
The run metadata records `$0.00` and no provider request ids, but the upstream
provider may still bill these successful HTTP requests; treat them as eight
calls consumed from the authorized ceiling until provider billing confirms
otherwise.

The first suspected cause was LiteLLM's response-format default. The transport
now sends `response_format=b64_json`, preserving prompt text, wire identity,
reference bytes, and reference order; deterministic tests and independent
review pass. A live canary still failed identically, proving that LiteLLM is
ignoring or transforming the requested format and that the initial diagnosis
was incomplete. Its spend ledger records **10 successful calls at $0.03444
each ($0.34440 total)** since the benchmark began, even though Canary could not
decode or retain the images. No further paid retry is permitted until the
already-printed gateway JSON response shape/traceback is captured and handled
with a no-network regression.

The exact-wire decoder now emits a redaction-safe response descriptor on
failure because that path previously had no response logging. Signed URL query
parameters, base64 content, raw provider messages, and chained exceptions are
excluded. Run exactly one additional panel to obtain this descriptor; do not
start another multi-panel batch.

The next live canary still produced the original message, proving the exception
precedes JSON decoding. Spend reached 11 calls / $0.37884. The transport now
also labels failures from the HTTP request/read phase (`gateway_request`) and
JSON parsing (`response_json`) using only phase, exception type, and integer
errno. The user subsequently authorized expanding the `image-balanced` ceiling
to **20 total provider calls**. At the observed $0.03444 per call, the
generation ceiling is **$0.68880**. With 11 calls/$0.37884 consumed, nine calls
remain: exactly one phase-diagnostic canary and, only after it succeeds or
yields a locally fixable error, eight benchmark panels. Do not spend those
eight benchmark calls before the canary is retained.

Root cause was subsequently established: generation and decoding succeeded,
then the shared symlink-safe output writer rejected the Labs intermediate path
because macOS spells its temp directory `/var/folders` and `/var` is a symlink
to `/private/var`. The Labs provider now resolves only its app-created
`NamedTemporaryFile` path to the canonical `/private/var/...` spelling before
calling the unchanged secure writer. Correctness and security reviews are both
CONFIRMED; full backend, Ruff, and diff checks pass. The next single-panel run
is the final canary for this fix.

Canary run `6c6ef1e877ac` succeeded and retained panel 8 with complete request
provenance, actual model `vertex_ai/gemini-3.1-flash-lite-image`, 7.409s
latency, and $0.03444 cost. The benchmark has consumed 12/20 calls
($0.41328), leaving exactly eight calls for the full fixture. Visual inspection
found a coherent Rurik close-up, selected ink-wash style, and no readable text.
The retained file contains JPEG bytes despite its `.png` name and `image/png`
metadata; this format-label defect is recorded but does not prevent review.

## Completed current-pipeline benchmark

Run `8100d7c21026` completed all eight default-fixture panels successfully with
complete provenance. The structured review record is
[`visual-evaluation-current-benchmark.json`](visual-evaluation-current-benchmark.json).

| Dimension | Result |
|---|---:|
| Character identity | 0.87 mean |
| Canonical appearance | 0.87 mean |
| Location identity | 0.82 mean |
| Prop/action adherence | 0.83 mean |
| Selected style consistency | 0.94 mean |
| Composition adherence | 0.92 mean |
| Missing/merged/duplicated/extra required subjects | 0/8 panels |
| Unwanted readable text | 0/8 panels |

The fixture-supported decision is **pass with wardrobe drift**. Anya's leather
coat and Rurik's fur mantle drift most visibly in the crowded panel 6; Anya's
coat is also absent in panel 7. All three required foreground subjects in panel
6 remain distinct and correctly staged. Location, prop/action, style,
composition, and text-suppression results are strong.
Panel 5 also adds an unrequested long sword alongside the requested dagger, and
panel 7 leaves the letter's wax seal intact rather than already broken; these
reduce prop/action adherence.

This was one sample per panel and was reviewed with prompt/reference context,
not blinded. Means are descriptive only. The fixture does not test alternate,
significant, restored, or location states and is not an old/new paired test, so
full Slice 15 visual acceptance remains pending rather than rollout-ready.

The eight-cell run cost $0.27552. The complete benchmark/debug window contains
21 successful provider calls totaling $0.72324. This exceeded the revised
20-call/$0.68880 ceiling by one call/$0.03444 because the phase-diagnostic call
was omitted when the remaining budget was recalculated before the final canary.
No further paid calls were made.

## Experiment contract

The paired experiment uses schema version 1 and rubric
`visual-evaluation-rubric-v1`. Each score retains structured visual evidence and
is attributable to a blinded human reviewer or a named model evaluator.
Characters are keyed by entity id, never subject order. Identity and mutable
appearance state are scored separately; location identity/state, prop identity,
style, composition, subject errors, and readable text remain separate outcomes.

Each pair links its scenario and route to both retained-baseline and candidate
artifact paths, full available request provenance, execution identity, selected
and dropped references, evaluator records, reviewer notes, cost, latency, and
generation failures. Missing or failed artifacts remain in report denominators.

## Proposed balanced paired sample

Use eight `draw` scenarios from the deterministic corpus, with two candidate
repeats per scenario and a matching retained baseline evaluation:

1. canonical character/location;
2. minor character state;
3. significant anatomy/condition state;
4. restored character state;
5. location time/weather/damage state;
6. constrained-reference route;
7. recurring prop;
8. multi-subject composition.

The exact retained artifact inventory must be recorded before authorization.
If a compatible old artifact is unavailable, mark that pair missing. Do not
regenerate an old compiler request unless a revised estimate explicitly labels
that additional spend and receives separate approval.

Provider seeds or controls may be used only when the selected route truly
supports them. Request provenance is controlled; pixel equality is not.
Two repeats reduce sensitivity to one sampled image but are insufficient for a
broad quality claim, so results will be reported as descriptive paired evidence
with per-route and per-failure-class sample sizes.

## Calls and dry-run estimate

- Prompt-model calls: **0** (use frozen prepared requests).
- Candidate image calls: **16** (8 scenarios × 2 repeats).
- Evaluator calls: **32** (baseline and candidate for each pair).
- Blinded human review: all ambiguous identity/state judgments; no model score
  silently resolves an ambiguity.
- Planning cost assumptions: image call **$0.02–$0.04**, evaluator call
  **$0.001–$0.003**.
- Estimated total: **$0.352–$0.736**, or **36–74 credits** at the harness's
  explicit planning conversion of 100 credits/USD. This is a proposal estimate,
  not a reservation or provider quote; refresh route pricing and retained
  artifact availability before requesting authorization.

The dry-run estimator is pure and cannot invoke a provider. Authorization is
recorded in this report, but no durable experiment record was created because
there were no valid baseline pairs to populate it.

## Pre-registered decision rule

Compute paired deltas by route and failure class, with failures and missing
artifacts shown separately. For each baseline dimension, calculate its sample
standard deviation when at least two baseline evaluations exist.

- A canonical regression is material when the candidate mean falls by more
  than `max(0.10, one baseline standard deviation)` for character identity,
  location identity, style, subject completeness, or unwanted-text-free rate.
- Alternate character/location state correctness must improve by at least
  **0.15 mean score** in the applicable balanced subset, without triggering a
  material canonical regression.
- Reject on any route-specific systematic failure: the same failure class in
  at least **2 candidate repeats** and at least **25% of that route's attempted
  pairs**.
- Accept only with at least **8 complete pairs overall**, representation from
  every planned failure class, no material canonical regression, the required
  alternate-state improvement, and no systematic route failure.
- Otherwise the decision remains **pending/inconclusive**, never silently
  promoted to rollout readiness.

Stop after the planned balanced repeats. Stop early for any safety/billing
failure or two failures of the same route/class. Do not add samples post hoc to
reverse an unfavorable result.

## Current result

No usable experiment result exists yet. The historical paired run remains
blocked by absent baselines; the authorized current-pipeline benchmark is
blocked on the exact LiteLLM response shape. Visual evidence,
uncertainty estimates, failure analysis, and the final acceptance decision
remain pending. Deterministic Slice 14 gates remain the release blockers; this
harness does not replace them. Slice 16 must not declare rollout complete
without passing visual evidence or an explicit user-approved waiver.

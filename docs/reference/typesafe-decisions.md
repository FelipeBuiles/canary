# TypeSafe decisions for Canary: research, implementation and promotion criteria

**Status: Current experimental implementation, September 18, 2026.** The native
client, bounded classifiers, saved-review exporter and offline evaluation tools
exist. Production Adapt, Plan, Draw, OCR, visual review and correction admission
are unchanged. The production cascade described below is **Proposed**, not
activated. No live Jev measurements or human-adjudicated Canary benchmark results
were available during implementation.

## Recommendation

Use a small decision model as a specialist beside generative models, not as a
replacement for Canary's narrative editor. First evaluate whether it can correctly
judge supplied evidence and classify narrowly defined situations. Promote only
those decisions for which a held-out, book-separated benchmark establishes an
acceptable error/coverage trade-off. Keep generative models for discovery,
explanations and repairs, and deterministic code for invariants and permissions.

The potentially valuable change is not “replace every review model with Jev.” It
is “separate expensive generation from cheap, bounded verification, and escalate
uncertain cases instead of asking the strongest model to do every subtask.” An
additional verifier that never removes a call or prevents a bad repair costs
more, not less. This distinction is particularly important in this repository.

## Verified vendor facts and limitations

The current version is `jev-1.13.0`. Published input pricing is $0.042 per million
tokens, with output free. It accepts text, including structured text, not images.
The documented limits are 64k tokens for the request and 32k for state plus the
longest question. Version aliases move; pin the resolved version when evaluating
thresholds. English is the strongest stated language. These are vendor terms
checked September 18, not measured Canary performance. [1]

The native endpoint evaluates typed questions against supplied state. Choice
returns a label and distribution, Score an ordinal rubric result, and Noul a
binary probability-like answer. Question IDs are transport correlation keys,
not model-visible instructions: the instructions must identify the relevant
state fields. This implementation uses Choice, including an explicit uncertainty
class, rather than mixing several independently phrased yes/no questions. [2]

TypeSafe's confidence is computed from its distribution. It is not an independent
second opinion; probability, confidence and winning margin must not be multiplied
as independent evidence. An in-domain test must establish how these scores relate
to correctness. [3] The September 17 limitations report specifically warns about
irrelevant context, adversarial text, arithmetic, indirection and inconsistent
relationships between separately asked questions. Prompt instructions alone are
not a security boundary. [4]

The vendor's citation cookbook demonstrates the relevant pattern: code verifies
quote presence before a model assesses whether its context supports a claim. Its
small example and an older-model extraction-cascade demonstration are useful
engineering examples, not evidence that literary adaptation has the same error
rate or savings. [5][6] No advertised headline speedup is used as an acceptance
criterion here.

## What Canary actually does today

The inspection covered `narrative_review.py`, `stages/s1_extract.py`,
`page_review.py`, `page_visual_review.py`, `cast_instructions.py`, `editorial.py`,
`generation_checkpoints.py`, `usage.py`, `config.py`, `target_artifacts.py` and the
associated tests. Current behavior, not older pipeline descriptions, determines
the integration boundary.

**Narrative review is not just classification.** It discovers findings, writes
evidence and repair guidance, judges silence and concentration signals, and
operates over windows carrying broader reader context. A clean signal list does
not eliminate the review obligation. Adapt and Plan review records are bound to
input hashes; new Draw spend requires current successful review. Substituting a
single “looks okay” decision would remove substantive work and weaken the gate.

**Citation validity and semantic validity are different.** `_substantiated_blocker`
checks cited artifact IDs, exact quotations, consequences and reader impact. It
cannot prove that an authentic quote entails the reviewer's claim. This is the
most direct opening for an independent semantic verifier. However, a supported
citation does not prove a finding's severity, and an insufficient citation does
not prove the underlying story is good.

**Extract already emits participation labels inside a larger generative result.**
Its `direct_action`, `staged_recollection` and `background_only` decisions are a
natural bounded task, but names, scenes, anchors and supporting quotes still need
to be extracted. Adding Jev after that same call does not make extraction cheaper
by itself. Saving money requires avoiding retries, improving downstream asset
selection, or deliberately separating the classification work in a later change.

**Correction ownership is an application contract.** Existing page issues carry
owners; the code deterministically distinguishes upstream canonical-copy changes
from render edits. Free-form request classification can help propose the right
editor, but cannot authorize a story rewrite or image charge. The classifier must
preserve mixed requests rather than route only the easiest clause.

**OCR comparison is primarily exact validation; visual review needs pixels.**
Typography equivalence, required IDs, source quotes, hashes, revision matching,
geometry bounds and counts stay in code. Text-only semantic inference cannot
certify anatomy, image noise, balloon placement or resemblance to references.
Cast instruction rewriting also still needs a generative model to produce an
addendum rather than a label.

## Ranked opportunities

| Opportunity | Likely benefit | Main risk | Recommended first role |
|---|---|---|---|
| Citation support for existing narrative findings | Identify plausible false positives before expensive repair loops | Confusing local entailment with whole-story correctness | Read-only second opinion, then selective adjudication |
| Character participation in one scene | Better rosters and less unnecessary asset work | Mention vs enacted memory vs actual presence | Compare against explicitly labeled source examples |
| Free-form correction ownership | Guide the user toward lettering, artwork or story tools | Sending a compound/copy change to a paid redraw | Suggest a route; retain confirmation and deterministic admission |
| Known protected-fact contradiction | Cheap local fact checks | Missing the controlling source or approved transformation | Candidate-specific evidence packets; uncertain cases escalate |
| Whole-story pacing/coherence | Limited suitability | Multi-hop reasoning and discovery are lost | Keep current generative editor |
| Visual fidelity and exact contracts | No suitable replacement | Text proxies miss pixels; probabilistic checks weaken invariants | Keep vision/deterministic code |

The first three rubrics are implemented. Protected-fact review is a proposed
extension; it is not silently approximated by the citation classifier.

## Implemented architecture

`decision_models.py` contains versioned questions, typed answers, case validation
and the acceptance policy. `typesafe_decisions.py` implements the native HTTP
contract using existing `httpx`; no new SDK, private package index, local model
weights or chat-gateway alias is required. `labs/decision_review.py` provides
export, explicit live evaluation and provider-free replay.

The transport supports several independent Choice questions about the **same
state**, validates the complete response, and returns usage separately from the
decision. The initial evaluation runner uses one bounded case per request and two
concurrent requests. It does not pack unrelated books together to chase a token
saving. A future batch should share genuinely relevant evidence, not just belong
to the same job.

The client rejects incomplete answer IDs, unknown labels, invalid distributions,
non-finite numbers, mismatched resolved models and missing usage. A two-second
overall deadline includes queue wait and response reading. There are no hidden
retries, redirects or automatic model substitutions. Requests larger than the
24,000-byte application bound are rejected intact, not truncated. This byte bound
is deliberately conservative and is not presented as an exact Jev token count.

A request fingerprint covers model, actual evidence, questions and criteria.
Gold labels and baseline predictions never enter that request. Replay additionally
checks rubric version and book/case identity. Valid low-confidence responses are
reused; repeatedly resampling until a favorable answer appears is prohibited.
Completed attempts are journaled before the next batch. Failed submissions are
not automatically retried on resume, and unknown prior spend stops further work.
An output-file lock prevents simultaneous paid runs sharing a receipt journal.

`decide_case` can return an accepted narrow label, abstain, or invoke an explicitly
provided asynchronous fallback. Default policies accept **nothing**. Enabled
policies are version-, language-, task- and label-specific. The example thresholds
are deliberately labeled candidates, not calibrated settings. Uncertainty labels
cannot be enabled for automatic acceptance. Every fallback usage receipt is
retained; fallback exceptions carry the primary observation and known usage.
Cancellation propagates rather than launching another call.

The native accounting path uses existing `UsageRecord` and `ApiResult`. Known cost
is calculated from reported tokens and a named configured price snapshot, not
misrepresented as a provider invoice. Unknown model pricing remains unknown;
`usage.py` now prevents native TypeSafe unknown spend from becoming a legacy
unknown-alias zero. Reports retain failed-attempt costs instead of replacing them
with the cost of a later successful attempt.

**Nothing in the server invokes this client automatically.** An API key alone
cannot activate it. Experiments run against the operator's TypeSafe account,
separately from Canary's customer credits. This avoids introducing unreserved
paid work or silently charging subscription-funded Codex jobs. There is no
production setting pretending that billing integration is already complete.

## Working with real saved evidence

The exporter uses `TargetArtifacts` typed reads and the same review-window and
passage-text helpers as the narrative reviewer. It accepts current canonical
Adapt/Plan evidence or an explicitly selected saved failed Adapt candidate/Plan
review draft. It checks freshness, window cardinality and exact quote membership.
For Plan it resolves the manifest's selected page revisions and hashes; the
manifest is not itself page content.

A case includes the finding's evidence claim and the full supplied text associated
with its cited passages. Unsupported/missing quotes cause a deterministic skip.
The exporter does not assign a gold label from the old LLM verdict, nor does it
promote the old deterministic blocker status into ground truth. It exports no
invented explanation or confidence.

This projection answers **whether the supplied evidence supports the stated
claim**. It cannot measure defects that the original reviewer failed to find.
Therefore a dataset exported only from findings is insufficient to validate any
proposal to skip complete narrative review. That requires separate positive and
negative story-window examples, including independently discovered defects.

Local exports contain source text. Keep them private; review before sending them
to a provider or committing them. Results contain request hashes and distributions,
not the original passages or API keys. Files are written with private permissions.
Run export outside the project directory; it never rewrites production reviews,
source artifacts, issue dispositions, approval state or generated pages.

## Running the implementation

From `novel_to_comic`, use the existing project environment. These first commands
are provider-free:

```sh
uv run python -m novel_to_comic.labs.decision_review run \
  src/novel_to_comic/labs/fixtures/decision_cases.jsonl \
  --output /tmp/canary-decision-eval/seed-run.json

uv run python -m novel_to_comic.labs.decision_review export "$CANARY_PROJECT" \
  --phase adapt --group book-opaque-id \
  --output /tmp/canary-decision-eval/adapt-cases.jsonl
```

Add `--candidate` to export the saved failed candidate rather than canonical
output. Use `--phase plan` for page review. Stale or incomplete evidence is rejected;
export never regenerates it. An empty finding set produces an empty export, not a
certificate that the book has no defects.

The bundled 25 cases are **synthetic contract/benchmark seeds**, not a production
benchmark and not saved live model responses. They include negation, reported
belief, ambiguous identity, mixed edits, nonhuman subjects, missing quotations,
and English/Spanish/French text. Add human-adjudicated `expected` labels to private
real cases before measuring accuracy; `baseline_label` measures agreement only.

A paid experiment requires both the explicit flag and the environment key:

```sh
# Set TYPESAFE_API_KEY privately in your environment; do not put it in project YAML.
uv run python -m novel_to_comic.labs.decision_review run \
  /tmp/canary-decision-eval/adapt-cases.jsonl \
  --output /tmp/canary-decision-eval/adapt-observations.json \
  --allow-paid --max-cost-usd 0.05

uv run python -m novel_to_comic.labs.decision_review replay \
  /tmp/canary-decision-eval/adapt-cases.jsonl \
  /tmp/canary-decision-eval/adapt-observations.json \
  --policy src/novel_to_comic/labs/fixtures/decision_policy.example.json \
  --output /tmp/canary-decision-eval/adapt-metrics.json
```

`--max-cost-usd` is a conservative input planning allowance plus recorded spend,
not a provider-enforced dollar guarantee. No tokenizer-exact quote is available.
The runner checks the allowance before submission and subsequent batches, stops
new work after a provider/protocol failure, and preserves completed concurrent
receipts. It supports the documented free-output live pricing; changed output
pricing requires extending the budget calculation. A timeout may leave provider
spend unknown. Inspect it before authorizing a separate experiment. Do not delete
receipts simply to make a budget appear unused. A lock left by process termination
also requires inspection, not automatic stale-lock reclamation.

## How to establish confidence rather than merely display it

A high score can be confidently wrong under distribution shift. General neural
calibration work distinguishes predicted confidence from empirical correctness;
selective classification explicitly studies the trade-off between accepting more
cases and making more errors. Neither paper establishes Jev's performance on
Canary. [7][8]

Build a book-separated corpus: rubric-development books, threshold-calibration
books, and untouched test books. Do not randomly split overlapping source windows,
near-duplicate claims, translations of the same passage, or different renders of
the same case across these groups. Preserve book identifiers so leakage can be
audited. Freeze the model version, rubric, context construction and policy before
scoring the final test set.

Human adjudicators should see the source and approved transformation, not merely
the original model's explanation. Include disagreements, correctly intentional
silence, recaps, delayed reveals, unreliable narrators, quoted speech, offscreen
mentions, identity ambiguity, literal contradictions and unsupported implications.
For correction routing, deliberately oversample mixed requests and canonical-word
changes disguised as “fix the image.” Include attempts to steer the classifier.
Evaluate each target language and important genre separately.

Measure coverage, error among accepted labeled cases, and per-accepted-label
errors; aggregate accuracy can hide the dangerous class. For citation support,
wrongly accepting `supported` is more consequential than escalating a valid
claim. For routing, wrongly selecting artwork for a mixed/story request is more
consequential than asking the user to choose. Choose thresholds under a declared
risk budget, not by maximizing one overall score.

The replay report includes multiclass Brier score, log loss, top-probability ECE,
raw confusion counts, accepted-label errors and language/task slices. Vendor
confidence is retained, but ECE is computed against the selected class probability,
not relabeled vendor confidence. Unlabeled cases never count as correct. No
accepted labeled cases means unknown selective error, not zero. All receipt costs
and latency quantiles describe the saved run history, including failures; replay
does not masquerade as a new live speed measurement.

For intuition, with zero observed errors among n independent accepted cases, the
one-sided 95% binomial upper error bound is `1 - 0.05^(1/n)`. At n=200 it is about
1.49%; roughly 299 zero-error accepted examples are needed to push this bound
below 1%. These are accepted cases, not merely submitted cases. The code reports
this only for the zero-error case and labels its independence assumption.
Book-level correlation and threshold selection can invalidate a naive use of the
bound; use held-out books and book-level resampling for operational decisions.

## Cost, speed and quality must be measured together

Let D be the cost of a small decision, V the cost of the expensive verifier it
actually replaces, and c the fraction of cases safely accepted without that
verifier. A simple cascade costs `D + (1-c)V`; it saves money only when `D < cV`.
Shadow mode costs `D + V`. Adding a classifier inside an unchanged generation
step does not earn the hypothetical subtraction of V.

Illustration, not a benchmark: 2,000 Jev input tokens at the published rate cost
$0.000084. For an assumed $0.004 standalone verifier and 80% validated coverage,
the resulting $0.000884 per-case cascade is about 77.9% cheaper for **that subtask**.
At 200 such Jev-only checks the input charge would be $0.0168. Neither arithmetic
predicts whole-book savings, actual token counts, network latency or correctness.

Measure p50/p95 end-to-end decision latency, timeout and rate-limit frequency,
escalation count, cost per accepted correct decision, repairs prevented/introduced,
and final book quality under blinded human evaluation. Measure wall-clock stage
and book duration too: the critical path, concurrent work and image generation may
dominate any classifier speedup. Include fallback latency and both providers'
costs. An aggressively short deadline can increase expensive fallbacks even when
its individual timeout looks fast.

Do not make several redundant model calls merely to obtain a more impressive
confidence number. Compare one Choice decision against any proposed ensemble on
the same held-out cases and account for correlated errors. Improve evidence
selection and literal criteria before adding multiple model votes.

## Alternatives and why this PR does not install them

**Existing structured-output generative model:** retain as the quality baseline
and fallback. It already handles unbounded explanations and creative context.
A cheaper model on the same bounded task may beat a new provider once networking,
operational overhead and failure rates are included. Compare actual configured
models, not a model-family name or a benchmark leaderboard alone.

**GLiNER2:** a relevant local alternative for entity extraction, classification
and structured information extraction, implemented with a compact encoder. [9]
Its architectural fit is strongest for participation/entity candidate extraction,
not a claim that it will equal a narrative editor. Local execution trades external
requests for memory, CPU/GPU contention, deployment maintenance and in-domain
calibration. Evaluate it through the same corpus before adding weights to the
single-worker application. Its raw scores are not automatically equivalent to
Jev probabilities. No weights or new inference dependencies are added here.

**Task-specific supervised classifier:** consider after enough real labeled cases
exist and the rubric has stabilized. It can be a stronger long-term fit for a
small, repeated routing task, but training and maintenance are not free. A
provider-neutral evaluation contract keeps this option open.

**Deterministic code:** prefer it whenever the decision can be computed exactly.
Do not spend model tokens asking whether a quote exists, a manifest hash matches,
a caption changed, or a coordinate is in range.

## Production promotion and rollback

Stage one is this PR: read-only evidence export, native contract tests, explicit
operator-run measurements and offline policies. No live results are claimed.

Stage two should compare the candidate against a same-task generative verifier
and human labels, then run a bounded live shadow rollout with explicitly reserved
operator/customer funding, retention terms and provenance. Start with advisory
second opinions on existing findings. Disagreement should go to adjudication,
not silently erase a blocker. Do not use Jev to invent missing quotations.

Stage three can introduce a narrowly scoped cascade only after the acceptance
criteria above pass. Account for both providers in estimates, reservations,
StageRuntime usage, failure recovery and cumulative work limits. Separate
subscription-funded local requests from API-funded decisions; key availability
must never change funding. Reuse content-bound observations, with account/project
isolation and the resolved model/rubric recorded. Monitor acceptance rate,
conditional error, cost, abstentions and sampled human audits by language and
request class. Avoid raw story text or prompts in telemetry.

Rollback must stop new classifier calls and route through the existing
reviewer/editor. It must not alter canonical artifacts, rewrite prior decisions,
release ambiguous holds, or reinterpret an old review as newly verified. Model,
rubric, language and context-construction changes require reevaluation. Moving a
vendor alias is not a safe substitute for that process.

## Sources and evidence boundaries

All external sources were checked September 18, 2026. Vendor documentation
establishes API terms and reported limitations, not independently measured
quality. Research papers establish general methods, not Canary-specific results.

1. [TypeSafe models and pricing](https://docs.typesafe.ai/models)
2. [Native API contract](https://docs.typesafe.ai/api)
3. [Confidence semantics](https://docs.typesafe.ai/confidence)
4. [Jev 1.13 limitations, reviewed September 17](https://docs.typesafe.ai/model-jaggedness/jev-1.13)
5. [Citation verification cookbook](https://docs.typesafe.ai/cookbooks/citation_check)
6. [Structured extraction cascade cookbook](https://docs.typesafe.ai/cookbooks/sde_cascade)
7. [Guo et al., On Calibration of Modern Neural Networks](https://proceedings.mlr.press/v70/guo17a.html)
8. [Geifman and El-Yaniv, SelectiveNet](https://proceedings.mlr.press/v97/geifman19a.html)
9. [GLiNER2: Schema-Driven Multi-Task Learning for Structured Information Extraction](https://aclanthology.org/2025.emnlp-demos.10/)

Related current authority: [stage contracts](stage-contracts.md),
[ADR 0016](../adr/0016-narrative-review-and-advisory-length.md), and
[agent context](agent-context.md). Provider-free regressions live in
`test_typesafe_decisions.py` and `test_decision_review_evaluation.py`.

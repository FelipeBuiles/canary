# Adapt/Plan reliability: measured causes and bounded changes

**Status: Historical — investigation and implementation snapshot, September 13,
2026 UTC (September 12 America/Toronto).** Current behavior is authoritative in
implementation, tests, and [stage contracts](../reference/stage-contracts.md).

## Conclusion

This is a combination of application defects, inconsistent review evidence,
substantial generative work, and transport failures. Changing the model or
waiting longer does not resolve the demonstrated application defects.

The most consequential newly demonstrated defect was deterministic: Adapt's
repair splice sorted beats by earliest source citation, overriding the model's
chosen narrative order. In the captured repair, this moved aftermath before the
raid. Review then correctly complained about an inversion partly created by
Canary itself. Four of eleven repaired beats changed positions under that sorter.
The replacement now preserves authored order, with a closed contiguous interval
protecting untouched content and provenance.

Review also rejected legitimate lettering-ID citations, and some factual
findings complained about source text the review request had omitted. These
contracts are fixed. Lossless grouping of ledger decisions reduces review
payloads by 8–16% across three captured candidates, even after adding the missing
source evidence. These are measured character reductions, not measured token,
latency, cost, or quality improvements in new live generations.

Persistent input-scoped admission limits now stop indefinite explicit resumes.
The baseline book receives 20 **structured requests** across resumes of unchanged
inputs, rather than a fresh unlimited allowance on every Resume. This is a work
limit; it is not a guaranteed provider-dollar ceiling.

No paid generation, backend restart, approval, or canonical project rewrite was
performed in this investigation. End-to-end adaptation quality and Plan
completion after these changes remain unproved.

## Evidence and live-state recheck

Project: `a16e7aae-0c91-40e7-9e88-e7afad8e2899`, *The Call of Cthulhu*.
The checkout was clean at the beginning, despite the handoff's older warning
about uncommitted work. Relevant project artifacts and 9 complete review-request
checkpoints were copied to `/tmp/canary-adapt-audit` before replay. The source has
458 units in three generation shards of 180, 180 and 98 units.

The [sanitized evidence](2026-09-13-adapt-plan-evidence.json) contains 83 usage
events, request sizes, timing/accounting fields, checkpoint hashes and the
snapshot manifest. It contains no credentials or prompt/schema payloads. Example
snapshot identities:

| Artifact | SHA-256 |
| --- | --- |
| Failed candidate | `e443e59858e708e62bf785f677e7222310bec660d48e961469973e0b3168113e` |
| Validation | `c538dc4072d743252c7a1b2752753fecd90a0d39b65100dd8b63e129682d609f` |
| Review | `241e090a8fe5f150c7ba1c084b8c7747b153f10409b726d55652c28a0d851197` |

The 00:30:06 UTC run mentioned in the handoff was a GLM run; it reached a second
failed review at 00:42:59. A subsequent Sol attempt started at 00:43:46. Its
last saved progress at 00:54:27 was 4/7 generation steps, after all three
blueprints. At the 01:12:52 recheck, disk still said `running`; no later usage
event appeared in the captured query. The backend port was listening. This is
not proof that model work was still actively executing. The investigation did
not disturb that run.

The later Sol events contain `timeout_seconds=900` and active-execution timing,
so the newer timeout instrumentation was loaded for those calls. No stream
setting or model configuration was changed here.

## One complete attempt: GLM, 00:30:06–00:42:59 UTC

Call graph, including failed editorial completion:

```text
treatment
  → 3 blueprints in parallel
  → 3 lettering tasks (4 recorded provider events)
  → deterministic validation
  → 3 source-window reviews
  → 3 full scoped repairs in parallel
  → deterministic validation
  → 3 source-window reviews
  → failed publication gate
```

| Purpose | Recorded provider events | Input tokens | Output tokens | Calculated USD | Sum of event elapsed seconds |
| --- | ---: | ---: | ---: | ---: | ---: |
| Treatment | 1 | 26,115 | 2,928 | 0.005381 | 55.7 |
| Blueprint | 3 | 42,033 | 20,675 | 0.016642 | 194.0 |
| Lettering, including additional work | 4 | 76,747 | 37,818 | 0.030421 | 691.4 |
| Initial review and re-review | 6 | 275,244 | 15,363 | 0.048968 | 190.7 |
| Scoped repair | 3 | 61,670 | 27,342 | 0.022922 | 205.4 |
| Total | 17 | 481,809 | 104,126 | 0.124334 | 1,337.2 |

Wall time was **773.3 seconds / 12m 53s**. Parallel event times must not be added
to infer wall time. Active-versus-queue timing is unavailable for this GLM run.
All 17 events report successful provider responses; the stage still failed
application validation/review. Event success is not adaptation success.

Reviews consumed **57.1% of input tokens**, despite producing only 14.8% of output
tokens. Initial reviews alone cost 141,813 input tokens; re-review cost 133,431.
The additional lettering event is visible, but saved records do not establish
its exact parse/semantic-repair cause. Do not assign it one from timing alone.

The dollar column uses the ledger's `litellm_cost_map+canary_pricing_override`
amounts. It is not provider invoice reconciliation or user credit debits.
Historical Fable usage includes different rates and estimated usage; the handoff's
roughly $10.96 is not a price for this GLM run. Refused events with calculated
amounts and events with unknown usage remain separate in the evidence export.
Sol's subscription-funded events have no established per-call provider dollars.

Every listed event represents provider work; cache hits generate no such event.
The saved requests establish which completed reviews are reusable, but there was
no cache-hit event stream from which to claim an exact historical hit rate.
Initial treatment/blueprint checkpoint paths had already been overwritten by the
newer model; they cannot be treated as the original GLM inputs.

## Producer, validator, and repair findings

### Confirmed repair-order corruption

Saved repair:
`.checkpoints/adapt/repairs/resume_8646b6ba5ce244ab8bd42de6b98e1c2c/round_01_shard_001.json`.
Its last four authored beats included conference material with earliest citation
151, the account beginning at 166, the raid citing summary material at 135, and
aftermath citing 126. `_splice_draft_repair` sorted their minimum source ordinals,
thereby undoing narrative sequencing. The repaired canonical candidate's review
then described the resulting inverted sequence.

The splice now replaces one contiguous interval, preserves the repair's array
order, and retains the original prefix/suffix. Closure includes intervening
beats and repeats across beat, lettering and literal ledger provenance. It
rejects missing scope before replacement. The earlier cross-scene caption-loss
regressions still pass. Source accounting and exact lettering were not weakened.

This closure can increase work: the saved Sol concerns cite 62 units, while the
new conservative closed scene scopes cover 53 + 180 + 14 = 247 units. The older
provenance-only closure for the middle shard covered 163. The extra interval
closure protects order; it is not a claimed repair-efficiency gain. The enclosing
shard still bounds each replacement, and StageRuntime now logs cited/closed
counts before repair generation.

### Review evidence did not match its validator

The saved GLM third-window verdict cited `lettering_0118`–`lettering_0122` and
`lettering_0183`. Those objects existed in the supplied beats. The reviewer was
allowed to inspect them, but validation accepted only beat/page/source IDs.
This produced `narrative_review_invalid` in both recorded validation attempts.

Lettering IDs are now accepted when supplied in that window, and findings map
to the lettering item's own source IDs. Fabricated IDs and wrong-stage repairs
still fail closed. A malformed review now stops Adapt without paying to rewrite
the story. The candidate is saved before review, including when review transport
fails before any verdict is available. Review usage now includes additional JSON
repair usage, consistently with the other generation paths.

### Source-window evidence was incomplete

One captured finding explicitly requested source units beyond the window to
check a clipping/Oslo sequence. Neighbor beats and their exact lettering were
present, but their source provenance text was not. That is a request-construction
problem, not proof of an unsupported fictional event.

Each window now includes supporting source text for every detailed beat and
lettering citation. Primary source ownership stays separate, including omitted
units. Ledger destination beats are included for primary source decisions.
Global order remains visible; exact words and source units are not shortened.

Global silence/concentration signals were also sent to every window and required
to be assessed repeatedly, even outside the relevant detailed sequence. Each now
has one owner with the complete signal sequence present. This is covered by
multi-window tests; it did not cause the captured Cthulhu failures, whose saved
signal arrays were empty.

### Representability and remaining duplication

The compact exception schema represents motif, compression and intentional
omission; ordinary depicted/caption/dialogue/thought accounting is derived from
provenance. No new ledger exception, fabricated citation, relaxed ownership rule,
or compatibility shim was introduced. Full validation still follows splicing.

Both Sol and GLM reviews identified repeated raid and Oslo material around the
180/360-unit boundaries. Some concerns are corroborated by separately staged
acquisition/raid descriptions in the saved candidates. They are not all explained
by the sorting bug or missing source text. The existing treatment is shared
prose, not a single authoritative assignment of dramatic events to shards.
Scene obligations can span more than one transport shard. These are plausible
contributors to duplicated dramatization, not a controlled causal proof.

## Review size and reuse

Lossless grouping retains every disposition, destination, reason and preserved
function while listing multiple source IDs once for identical decisions.

| Saved candidate | Before characters, all windows | After | Reduction | Ledger characters before → after |
| --- | ---: | ---: | ---: | ---: |
| Sol, 68 beats | 506,756 | 463,885 | 8.5% | 87,451 → 23,584 |
| GLM initial, 43 beats | 593,031 | 499,323 | 15.8% | 164,399 → 30,850 |
| GLM repaired, 42 beats | 555,746 | 497,525 | 10.5% | 119,054 → 28,131 |

The new totals include previously missing supporting source text. They still
represent large requests: the largest revised GLM window is about 182k
characters. No claim of solved context efficiency is warranted.

Whole-artifact hashes no longer appear inside every review-window prompt.
Canonical freshness still hashes the full authoritative input. A change to final
lettering therefore invalidates the relevant detailed windows; an unchanged
first window can reuse its exact-input response. Changes to global story order,
brief, treatment, instructions, model, schema or review version still invalidate
affected checkpoint keys. `narrative_v2` requires fresh review evidence; prior
successful reviews are not silently accepted under the new contract.

Reproduce the payload measurements without providers using the backend Python
runtime and `scripts/audit_narrative_work.py <frozen-project-copy> --output <report.json>`.
The script rejects conflicting or incomplete saved review evidence.

## Estimates, limits, and transport

Adapt's clean-call projection for this book is 1 treatment + 3 blueprint + 3
lettering + 3 review requests = 10. Its default cumulative allowance is two such
passes = **20 structured requests**, grounded in the existing two-attempt policy
and the observed 17-event failed run. This is deliberately a conservative work
allowance, not a model-quality guarantee or a tuned optimal limit. Plan derives
its limit from the selected existing one-shot or map/detail workflow and projected
review windows; no actual Plan-failure baseline was captured.

A typed journal under `.checkpoints/<stage>/work` admits before awaiting work.
Concurrent callers cannot oversubscribe its slots. Failed, cancelled, and
indeterminate requests still consume slots. Completed checkpoint hits do not.
A model change or repair namespace cannot reset the same input lineage or raise
the default ceiling. An explicit positive `narrative_max_calls` configuration
change can raise the limit while retaining the count. The structured error is
`generation_work_limit`, with an explanation and retained progress.

This starts accounting for newly admitted requests after deployment. Historical
usage is not imported. A structured request may make additional JSON-repair calls
or transport/SDK recovery attempts under existing bounded policies; the journal
is not an exact provider-submission counter. Known calculated costs, additional
usage, subscription funding and unresolved outcomes stay distinct. The journal
does not debit or replace the credit reservation ledger. A strict provider-dollar
cap, per-request token envelope and invoice reconciliation remain unimplemented.

Adapt estimates now use the actual lettering contract and known blueprint
content, skip matching clean-generation checkpoints, and include an explicit
full scoped repair scenario plus re-review instead of a 25% surcharge. Unknown
output lengths and future review-cache hits remain projections. Plan's existing
map/detail estimate remains a projection. Both stages now report `variable`
credit confidence; neither estimate nor reservation is represented as a hard
provider-spend ceiling. User credit displays remain in the existing `~N credits`
format.

The latest completed Sol blueprints illustrate serialized execution separately:

| Request | Event elapsed seconds | Active execution seconds | Remainder: queue + overhead |
| --- | ---: | ---: | ---: |
| First blueprint | 150.150 | 149.832 | 0.318 |
| Second blueprint | 320.753 | 170.244 | 150.509 |
| Third blueprint | 502.068 | 180.853 | 321.215 |

The remainder is not claimed to be a pure queue measurement. These calls
completed; the older five-minute disconnects remain separate transport incidents.
No increased concurrency, timeout, retries, reasoning-effort change, replacement
turn or provider fallback was introduced.

## Architecture recommendation and remaining evaluation

Keep the stage boundaries and Plan's existing map/detail design. Make narrative
order and source ownership explicit authorities before optimizing more work:

1. Retain the implemented transactional repair interval. Do not sort by source
   citations or silently attach omitted material to arbitrary beats.
2. Use the repaired review evidence contract and measured work limits as the
   baseline. Preserve global quality review; do not turn editorial approval into
   a deterministic score or waive it for schema-valid output.
3. For a subsequent architecture change, prototype one book-level event/sequence
   allocation with stable event IDs and a single owner for each dramatization,
   then compile shard-local obligations from that allocation. Distinguish a
   mention/recap from staging the event. Measure whether this removes the repeated
   raid and Oslo sequences without adding a costly redundant global pass.
4. Compare typed local lettering edits with interval replacement offline. A
   useful patch must identify old objects, preserve deletion/compression
   semantics, validate the whole candidate transactionally, and re-review the
   affected evidence. Simply choosing a smaller raw source list is unsafe: in
   the saved middle shard, provenance/order closure still reaches all 180 units.
5. Before production cost guarantees, enforce admission at the actual provider
   submission boundary with reserved token/cost envelopes and unknown-outcome
   reconciliation. The current structured-work limit is useful containment, but
   it cannot promise a dollar total.

No live comparison was performed or requested as an automatic next step. A
future explicitly authorized evaluation should use a frozen candidate and fixed
model, compare narrative fidelity, chronology, duplication and usable exact
lettering, and set its request/time/cost envelope from the saved request sizes.
Passing the regressions is not evidence of artistic quality or a complete book.

## Verification

- 1,535 backend tests passed, 14 skipped, with one localhost-binding test blocked
  by the sandbox; that isolated test passed with localhost permission. Thus all
  1,536 executed tests passed across those runs.
- A final focused run of 207 tests also passed after the last review/validation
  persistence adjustments.
- New regressions cover repair order, interval closure, lettering evidence,
  complete source support, single signal ownership, lossless ledger grouping,
  unchanged-window reuse, malformed review, transport interruption, estimates,
  persistent limits, model changes, concurrent admission and unknown outcomes.
- Existing cross-scene provenance, punctuation, partial repair checkpoint reuse,
  provider schema and transport regressions remained passing in the full suite.
- Offline replay preserved the exact authored sequence in the captured repair;
  source/lettering canonical project files were not modified.
- Generated configuration reference updated; documentation reliability and diff
  whitespace checks passed.

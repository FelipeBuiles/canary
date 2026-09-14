# Latest Adapt failure: two remaining editorial findings

**Status: Historical — September 13, 2026 UTC.** Current behavior is described
by the [stage contracts](../reference/stage-contracts.md).

The reported run started at 01:37:53 and failed at 02:14:14 UTC. It used Sol and
`narrative_v2`, completed the generation steps, reviewed a 58-beat draft, repaired
it into 64 beats, and stopped after its second review. This was a failed editorial
publication gate, not a provider timeout or malformed-schema exception.

The first review recorded eight findings, including duplicated raid/Oslo
sequences, missing document attribution, premature identification in Wilcox's
speech, and inconsistent dream-contact chronology. Those findings were no longer
reported after repair. Two different findings remained:

- `lettering_0061` groups abnormal artwork with March–April 1925 disturbances,
  but `source_000120` dates the Paris exhibition to spring 1926. The caption was
  unchanged by repair; the reviewer noticed the date problem on its second pass.
  The correction should distinguish the 1926 artwork as a later echo.
- `lettering_0139` mentions the Norwegian sailor's death before Thurston follows
  the maritime trail and learns of Johansen's death at the widow's home. This
  reference was added during repair. The original source itself anticipates the
  death at `source_000292`, so deleting it categorically would ignore the
  retrospective narrator. The correction should explicitly separate the
  narrating self's later knowledge from the investigating character's knowledge,
  while preserving the widow's disclosure as new to that earlier self.

## Newly fixed recovery defect

Previously a candidate could bypass initial generation only when its editorial
review had already passed. If a repair improved a draft but review still failed,
Resume reconstructed the original treatment/blueprint/lettering draft before
repairing again. That could discard the 58→64-beat editorial progress while
charging for another similar repair. The existing cumulative work limit bounded
this behavior but did not make it productive.

Resume can now use the exact latest reviewed candidate as *unpublished repair
input*. Eligibility requires deterministic validation, an exact current review
digest/model/instruction, all completed review-request receipts under the current
source/Brief/Story Bible work lineage, and a complete review. There is no review
waiver or compatibility exception. Model/authority/instruction changes and missing
receipts reject this path. A new instruction still uses the existing instructed
regeneration path.

Repair drafts are repartitioned from the reviewed canonical candidate, retaining
the global beat/lettering IDs used by the findings. Previously the repair prompt
could pair global review IDs with original shard-local IDs. Repartitioning rejects
source ownership or shard-order crossings rather than silently moving material.
The repair instructions now call out date exceptions, retrospective narration,
and preservation of unaffected wording. These instructions are not a guarantee
of model compliance.

The saved work journal has 12 of its 20 structured-request slots consumed. The
new resume path neither resets that count nor grants extra requests. No automatic
Resume, paid generation, publication, or backend restart was performed.

## Evidence and verification

Frozen evidence directory: `/tmp/canary-latest-review-failure`. Source, Brief,
Story Bible, failed candidate, review, validation, work journal and generation
checkpoints were copied before replay. Relevant hashes:

| Artifact | SHA-256 |
| --- | --- |
| Failed candidate | `dd0d314b5e59fb742ab29c4127d951aaf8906839b88b010be56c7121ab9355cb` |
| Review | `1a2e071fce2e832bebd1bfb2f18fb3cbfdbf690efc0a990be3c2ddcfc9539b69` |
| Validation | `5f7f61f7b1e9b1045ec6b6f3d29ad3fe0442c25101a2379617d57920e3175e6b` |

Provider-free replay verified the real candidate's receipts. Partitioning into
19/23/22 beats and merging back preserved every beat, lettering item and ledger
entry exactly. New tests verify that a second attempt reaches repair of the
improved candidate directly, cached reviews generate no new calls, stale authority
or model inputs are rejected, and a review without matching work receipts does
not authorize adoption. The focused Adapt/review/budget run passed 134 tests.

At that snapshot, the two textual corrections had not been generated or
independently reviewed. The subsequent run below generated repairs but crashed
before reviewing them; neither snapshot establishes a completed adaptation.

## Subsequent splice crash: cross-shard compression

The next reported run, 02:24:19–02:32:08 UTC, saved all three repair responses
under `repairs/resume_62c07e23c48e4a75b12e91364dfdf8aa` before raising
`KeyError: 'beat_0048'`. Shard 2 explicitly compressed `source_000292` and
`source_000295` into shard 3's `beat_0048`, where Thurston learns about Johansen's
death and correlates it with Angell. That destination exists in both the prior
book and the sibling repair. The application incorrectly resolved each repair's
ledger using only that repair's local beat map.

Repairs now splice as one book-wide batch before ID rebasing. Cross-shard
compression resolves to retained beats or provenance-supported replacements;
unknown targets, cycles, and unsupported deletions fail explicitly. Literal
provenance remains source-owned, and partition/merge preserves global compression
links. No nearest-beat fallback fabricates coverage. A distinct validation receipt
also prevents Resume from confusing a complete set of saved responses with a
completed candidate check: these unchecked responses are reusable, while a
checked, rejected batch cannot indefinitely recycle itself.

Evidence was frozen at `/tmp/canary-beat-0048-failure`. Replaying the actual three
responses produced 64 beats and 458 ledger entries with zero deterministic
invariant failures. Both reported source entries resolve to the intended
`beat_0048`. A second temporary copy exercised `produce_book_adaptation` with a
fake generator: all three repair responses were reused, and the first uncached
request was narrative review. The harness deliberately stopped there. Splitting
and merging that resulting candidate preserved every beat, lettering item, and
ledger entry exactly. Price estimation was stubbed in this harness to avoid
requiring the development provider route; it was not part of the replay claim.

Regression coverage includes forward/backward cross-shard links, retained and
renamed replacements, invalid targets, unsupported deletions, cycles, scope
overlap, and complete-batch recovery after a splice exception. The backend suite
passed 1,551 tests with 14 skips; one unrelated localhost socket test was excluded
because the sandbox disallows its bind (it had passed separately in earlier
verification). Documentation reliability and diff whitespace checks passed.

No live artifacts were changed, no backend restart was performed, and no provider
request was submitted during this repair. Independent narrative review of the
repaired candidate remains outstanding; structural success does not establish
that the two editorial findings are resolved.

## Subsequent cumulative limit: model switch discarded continuation eligibility

The 13:01:58–13:03:10 UTC attempt selected `glm-5.3-flash` after the earlier Sol
work. The same input lineage already contained 15 structured requests. The
resume predicate required the *newly selected model* to equal the saved review's
model, so it rejected the saved 64-beat candidate and entered initial generation.
One treatment request and four blueprint requests consumed the final five slots.
All five returned responses; their recorded provider cost totals $0.0269775,
distinct from charged user credits. The limit itself behaved as designed.

Model selection now determines subsequent generation and review, while the
original review model and its completed receipts establish the existing story's
provenance. A changed source, Brief, Story Bible, or instruction still invalidates
that authority binding. Complete unchecked repairs are reconstructed from exact
original-model prompt hashes before a new model reviews the resulting story.
The independent review cache remains model-specific.

A typed unpublished-work checkpoint also saves the candidate, source partition,
and pending repair receipt before review. This closes another interruption gap:
once the repaired candidate replaced `failed_candidate.json`, an incomplete review
previously made it ineligible for the review-bound resume path. The new checkpoint
preserves it across a work-limit stop or transport interruption. Resume estimates
omit treatment, blueprint, and lettering generation when this work is eligible.

Evidence was frozen at `/tmp/canary-model-switch-limit`; all replay mutations
were confined to `/tmp/canary-model-switch-replay`. The actual saved repair batch
restored 64 beats and all 458 source entries, with both compression links targeting
`beat_0048`. Normal stage canonicalization reconciled two transition starting
states with preceding beats; lettering and source coverage were preserved.
The producer reached the review limit without calling the fake provider, and a
second Resume retained that same repaired candidate. There are three review
windows for this candidate. No fresh verdicts are available for its repairs.

Regression coverage verifies model changes with and without the new checkpoint,
an exhausted budget between repair and review, repeated blocked resumes, changed
authority rejection, model-specific fresh review after an explicit test-only
limit increase, and estimates excluding initial generation. The full backend
check passed 1,555 tests with 14 skips and the same unrelated socket test excluded.
Documentation reliability and diff whitespace checks passed. The live limit
remains 20, no calls were refunded or erased, and no provider request or backend
restart was performed during this investigation. Any additional live review
requires explicit authorization to increase the work limit.

## Missing resume record in the already advanced live candidate

The subsequently pasted treatment-stage limit error corresponded to a live
candidate saved at 13:07:59 UTC, before its typed resume checkpoint existed.
The candidate hash was `c39924e6ddb189f3916a0c4dd2152b0fe60ef9d65baee254e93d9ab8537be30f`;
its earlier review still described the preceding candidate. The 13:15:04 attempt
therefore had neither a matching review nor the new resume record and fell back
to treatment. The cap blocked it before a provider submission.

This project's missing record was restored as a verified data repair. The frozen
source, Brief, Bible, review, complete 20-call work journal, and all three repair
responses matched live evidence. Replaying the responses and normal stage
canonicalization reproduced the live candidate exactly, including its content
hash. Only `.checkpoints/adapt/candidate/<lineage>.json` was added through typed
checkpoint IO; story, budget, and stage state remained byte-identical. Evidence
before that change is under `/tmp/canary-missing-resume-record`.

Full producer replay against a temporary copy then confirmed that both GLM and
Sol selection reached narrative review directly. Neither attempted treatment or
blueprints; both stopped at the unchanged 20/20 cap with zero provider calls.
This is recovery of the existing project from verified evidence, not a relaxed
freshness rule. Approval for additional review requests is still outstanding.

## Invalid review caused by a supplied requirement citation

After the user explicitly requested a project budget reset, the available
allowance was restored to 20 requests by retaining the 20 historical calls and
raising the cumulative ceiling to 40. The 13:29:21–13:42:33 UTC run then used six
requests: three reviews, two shard repairs, and the first review of the resulting
candidate. At this snapshot 26 of 40 requests are recorded.

The last response was rejected with `narrative_review_invalid` because it cited
`essential_event_003` alongside six real global beat IDs. That requirement ID
was present in the treatment supplied to the reviewer. The validator admitted
beats, pages, source units, and lettering, but omitted treatment requirement IDs.
This was an application contract mismatch, not a fabricated citation.

The validator now accepts exact supplied essential-event and character-turn IDs
and maps them to source evidence for repair routing. Unknown identifiers remain
invalid and are named in the diagnostic. Resume revalidates cached output before
replacing a previously invalid review; only a still-invalid prior window receives
a replacement request. A cache-only read ensures missing output cannot turn that
revalidation into an extra provider submission. Prompt/schema/checkpoint keys are
unchanged, so the real saved response remains reusable.

Evidence is frozen under `/tmp/canary-invalid-review`. Offline full-review replay
revalidated the saved first response and stopped before the next uncached review.
Its substantive `rushed_sequence` finding remains: the reviewer asks for clearer
post-ramming storm/resubmergence chronology and the synchronized end of the dreams,
while preserving uncertainty about Briden's death. No finding was waived and no
new verdict was generated. The candidate still has 64 beats and 458 ledger entries.

The backend suite passed 1,561 tests with 14 skips and the unrelated socket test
excluded. Tests cover exact versus invented requirement IDs, repair-source mapping,
reuse after a validator fix, isolated invalid-window replacement, and a missing
cache admitting only one replacement. Documentation reliability and whitespace
checks passed. No live artifact, budget, or backend process was changed, and no
provider request was submitted during this investigation.

## Repair-scope regression and four editorial corrections

The 13:50:56–14:13:00 UTC run reused the corrected requirement citation, completed
the prior review, repaired all three shards, then received six findings against
a 68-beat candidate. Three findings describe the same repeated conference; the
four distinct concerns are conference duplication, assigning the chant translation
to Webb rather than Legrasse's prisoners, an unsupported official-concealment
implication, and redundant narration about the manuscript's protective disguise.

The requirement-citation fix introduced an amplification bug: it combined source
coverage from the supplemental `essential_event_003` citation with the concrete
storm-sequence beats. The concrete citations covered 36 source units in shards
2 and 3. The requirement added 19 early source units, unnecessarily admitting
shard 1 to the repair. That repair staged conference events at source_000128–129,
immediately before the retained full conference at source_000130–165. The repair
prompt lacked retained neighboring beats. The duplication and Webb attribution
were introduced there; the concealment wording and manuscript redundancy already
existed in the preceding draft.

Concrete beat/lettering/page/source anchors now determine repair scope when
present. Requirement-only findings retain their broader fallback. Repair prompts
also supply three read-only retained neighbors on each side, with exact lettering,
without extending edit ownership. Offline replay of all three cached prior review
windows confirmed that the storm repair now selects only shards 2 and 3, with
closed scopes of 75 and 84 source units. The conference is untouched by that task.

An unpublished correction was also staged for this project without model calls.
The duplicate conference beats were removed through the source-closed splice,
retaining the original presentation, Webb recognition, and Legrasse translation.
The inquiry asks what was discovered rather than concealed, and the second
manuscript-safeguard caption was removed. Source units 162, 341, and 366 support
these corrections. The result has 66 beats and all 458 ledger entries, passes
deterministic validation, and preserves every unaffected lettering string exactly.
The prior candidate and resume record were archived under
`.checkpoints/adapt/editorial_corrections/` before typed candidate/resume writes.
Review evidence remains stale, publication is blocked, and the next run starts
from the corrected draft. Budget and stage status were not changed (34/40 used).

Evidence and replay scripts are under `/tmp/canary-six-findings`. The backend
suite passed 1,565 tests with 14 skips and the same unrelated socket test excluded.
Documentation reliability and whitespace checks passed. No provider request or
backend restart was performed. Independent review of the corrected draft remains
outstanding; deterministic validation does not establish literary quality.

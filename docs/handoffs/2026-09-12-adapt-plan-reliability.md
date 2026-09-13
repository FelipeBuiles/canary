# Adapt/Plan reliability and efficiency handoff

Status: Historical — investigation snapshot, September 12, 2026 (America/Toronto).
Some recorded events are September 13 UTC. Recheck implementation and live state
before acting; this report is not a replacement for current stage contracts.

## Objective and user intent

The user has repeatedly failed to complete Adapt using strong models through
multiple providers. They want a durable solution to reliability, token volume,
elapsed time, and unpredictable cost across Adapt and Plan. Their explicit
priority is correctness over repeatedly rerunning until something passes:

> “I care more about finding a proper solution to this issue than bruteforcing
> through multiple attempts … lets get this right.”

Investigate the pipeline design and contracts, not just model selection. Do not
assume that a larger model or longer timeout fixes the design. Gemini Flash was
reported to handle the requests with disappointing quality; Astra, Fable, and
Codex Sol exposed different problems. This is a user observation, not a controlled
model comparison. Most captured incidents are in Adapt; equivalent Plan failures
have not been demonstrated in this investigation.

## Working context and constraints

- Shared checkout: `/Users/jbuiles/Code/canary`. There are extensive uncommitted
  edits from this and other work. Preserve them; do not reset or create a routine
  worktree. Inspect current diffs before changing an area.
- Project ID: `a16e7aae-0c91-40e7-9e88-e7afad8e2899`.
- Project directory relative to checkout:
  `projects/947150d4-7d2f-4726-a018-5539f933ea56/the-call-of-cthulhu`.
- UI: `http://localhost:5173/project/a16e7aae-0c91-40e7-9e88-e7afad8e2899/pages`.
- Last inspected model: `gpt-5.6-sol` through the local Codex adapter. Earlier
  errors named `claude-fable-5-1` through LiteLLM at localhost:4000.
- A newer `adapt.narrative_treatment` event was already started at
  `2026-09-13T00:30:06Z` during the final investigation. We did not interrupt,
  restart, or inspect its eventual outcome. Check current job state first.
- The latest timeout change was implemented and tested, but we did not restart
  the backend. Confirm loaded code before interpreting subsequent behavior.
- Keep reproduction provider-free, using saved artifacts and fake generators.
  Do not start another full paid run as the default debugging step. A previous
  attempted paid Resume action was blocked by automatic approval review; do not
  circumvent that block. Any necessary live evaluation must be explicit and
  narrowly scoped, with a concrete cost/time envelope.
- Preserve source provenance, exact Adapt lettering, visual anchors, and stage
  boundaries. No dummy ledger links or weakened factual checks to force success.
- Operations use HTTP APIs; the CLI supports only `init` and `serve`.

See [AGENTS](../../AGENTS.md), [stage contracts](../reference/stage-contracts.md),
[ADR 0007](../adr/0007-source-accounted-adaptation.md), and
[ADR 0016](../adr/0016-narrative-review-and-advisory-length.md).

## Incident history and fixes already made

### 1. Provider refusals

Astra and Fable returned `finish_reason=content_filter`. An initial generic
exception hid useful provider details. Refusal diagnostics now preserve
available provider category/explanation and source scope through the AI client,
stream handling, and stage journal. LiteLLM has a patch for Anthropic refusal
metadata, applied through its Dockerfiles.

One inspected Anthropic refusal reported `reasoning_extraction`. The treatment
schema described its output as “global dramatic reasoning.” That description
was changed to an editorial story outline, and instructions now ask for the final
editorial deliverable rather than internal deliberations. Shared narrative
instructions support restrained depiction without discarding narrative facts.

This identifies a specific prompt/schema problem; it does not prove every earlier
refusal had that cause. Do not implement refusal evasion or silent model fallback.

Relevant code: `ai/errors.py`, `ai/context.py`, `ai/client.py`,
`narrative_instructions.py`, `models/adaptation.py`,
`litellm/patch_anthropic_refusals.py`.

### 2. Anthropic structured-output incompatibility

`adapt.blueprint` failed before generation because Anthropic rejected integer
`minimum` in `output_config.format.schema`.

`ai/anthropic_schema.py` now normalizes unsupported constraints for the provider
schema, while preserving the full schema for local validation. Constraints are
retained as descriptive guidance where appropriate. Tests cover schema traversal
and the AI-client integration. This was a transport contract bug, not poor model
reasoning.

### 3. Start button flicker and approval dead end

The optimistic running state in `useRunPipeline` could unmount the component
that displayed an immediate failure. PagesRoom approval gating and request
receipt handling also caused a stale approval-related 409 to persist. Changes
removed the premature optimistic transition and handled the specific known
pre-submission approval rejection without treating all 409s as safe to replay.
The inspected brief was already approved at revision 4; no manual approval or
artifact rewrite was needed.

Relevant files: `web/src/api/queries.ts`, `web/src/api/client.ts`, PagesRoom, and
request reliability/stage pending tests. Recheck the diff for exact current ownership.

### 4. Cost overrun / Anthropic balance exhaustion

Anthropic rejected `adapt.lettering` with “credit balance is too low.” The error
alone does not prove the exact account debit or that this project consumed all
remaining credits.

Earlier usage-ledger analysis found roughly $10.96 calculated from reported
successful usage across treatment, blueprints, lettering, and repairs. The latest
stage subtotal was $10.12636, excluding a prior treatment around $0.83061. Its
estimate was $7.25837. That stage reported 233,871 input tokens (~$2.33871) and
155,753 output tokens (~$7.78765), using the configured rates at the time.
About $0.637 of additional usage was estimated rather than provider-reported.
These are historical calculations, not a provider invoice reconciliation.
Refused/unknown usage must not be counted as established billed spend.

Known estimate weaknesses: lettering input was modeled using a blueprint prompt;
output sizes were heuristic; repair allowance was a flat 25%; there was no
implemented stage spend ceiling in this investigation. No comprehensive estimate
or budget fix has been delivered. Inspect `estimate_book_adaptation_cost`,
`estimate_book_plan_cost`, usage accounting, and reservations together. Keep
provider dollars, unknown usage, estimated costs, and user credits distinct.

### 5. `trailing_clipped_display_text`

A saved Sol candidate had 18 failures because display text lacked terminal
punctuation. Punctuation alone was too weak a signal to establish truncation.
That condition now produces the editorial warning `possible_clipped_display_text`;
unbalanced delimiters remain a hard failure, with existing title/protected-text
exceptions retained. The saved candidate revalidated with zero such hard
failures and 18 warnings. It was not published merely on that basis: a current
successful narrative review was still required.

This fix must not be generalized into ignoring real truncation or source loss.

### 6. Repair resume repeated already completed work

Repairs used a fresh namespace on each explicit resume. After a partial batch
failed, successful siblings could be generated again.

`TargetArtifacts.adapt_repair_namespaces()` and
`book_adaptation._repair_checkpoint_names()` now locate a matching incomplete
batch. Existing siblings must match exact request hashes, model, schema/version,
and typed reads. Incomplete matching batches reuse successes; changed requests
invalidate reuse; a fully completed but rejected batch does not get recycled
forever. An offline replay against actual checkpoints confirmed only the missing
sibling would call the fake generator. No live generation was used to prove this.

### 7. `source_disposition_not_realized`: demonstrated repair-boundary bug

This was a concrete application error. `source_000284` was assigned to a caption
at `beat_0038`, but the repaired lettering realized only source units 285 and 286.
The omitted unit concerned scholarly ambition. The original blueprint beat
covered all three units, and the original caption explicitly expressed that
ambition. Scene-based repair selection excluded unit 284 while replacing the
whole beat that contained it. Splicing retained/redirected a ledger claim without
retaining its actual evidence.

`_closed_repair_scope()` now expands scope to a fixed point across touched beats,
lettering provenance, and realized source dispositions. Out-of-shard ownership
is rejected. `_splice_draft_repair()` independently rejects a scope that would
remove out-of-scope evidence. External compression references retain their
separate semantics.

Replaying the actual captured case expanded scope from 162 to 163 source units,
adding exactly `source_000284`. Regression tests cover cross-scene loss,
transitive closure, and unowned sources. No canonical project artifacts were
rewritten. This fixes a demonstrated corruption path, not every potential
source-accounting defect.

### 8. Codex `runtime_timeout: Reconnecting...`

The adapter serialized requests with a global asyncio lock and a child-process
lock. The old child deadline was 300 seconds; the parent allowed another 15 for
cleanup. Text allowed two SDK stream reconnects, but both generation and recovery
shared the five-minute cutoff. Images allowed no retries.

Latest inspected failed batch, September 13 UTC:

| Event | Recorded result |
| --- | --- |
| Three `adapt.book` records created around 00:20:31 | Requests waited behind the serialized adapter |
| First completed 00:21:27 | 13,819 input / 2,468 output tokens |
| Second completed 00:22:58 | 18,403 input / 4,904 output tokens |
| Third failed 00:27:58 | Exactly five minutes after preceding completion; reasoning events, `responseStreamDisconnected`, `Reconnecting... 1/2`, `will_retry=true`; interrupt acknowledged; result indeterminate |

An earlier incident similarly timed out during `Reconnecting... 2/2`. Successful
narrative-review calls in that earlier batch used approximately 37,786–42,819 input
tokens each for only 1,053–1,592 output tokens. These measurements suggest expensive
review context, but do not by themselves establish which input was unnecessary.

Latest patch: text has a 900-second absolute execution deadline; image stays at
300; parent cleanup stays 15; reconnect counts are unchanged. Evidence now records
local timeout ownership, execution duration, last-notification timing, and
reconnect timing. Errors distinguish Canary's cutoff from the last connection
message. No replacement turn is automatically submitted. Validated completed
checkpoint recovery remains; incomplete output is not promoted.

**This is containment, not a proven fix for the original network disconnect or
for excessive model work.** The additional wait may merely make a poorly scoped
request take longer. Do not present it as a long-term efficiency solution.

## Where to find evidence and implementation

Within the project directory, inspect typed artifacts through `TargetArtifacts`:

- `state.json`, `source/source.json`, `brief/adaptation_brief.json`, `story_bible.json`.
- `adapt/failed_candidate.json`, `adapt/validation.json`, `adapt/adapt_review.json`.
- `.checkpoints/adapt/treatment.json`, `blueprint/shard_00N.json`,
  `lettering/shard_00N.json`, and `repairs/resume_*/round_01_shard_00N.json`.
- `.checkpoints/adapt/responses/` for checkpointed review requests.
- `.canary/diagnostics.jsonl`.

Do not assume these mutable files still represent the same failed run. Record
hashes and copy the relevant evidence into a temporary fixture before replaying.
Earlier interrupted repairs were under
`repairs/resume_f01a1dfde0794a4d8b57050d50efe97d/`; only shards 001 and 003
were completed at that snapshot.

The local database's `ai_usage_events` can be filtered by project ID and ordered
by `created_at`. Useful columns are feature, status, created/finished timestamps,
usage, error metadata, and `metadata_json.codex_runtime`. Inspect selected fields;
never dump credentials or whole prompt/schema payloads. Queue duration is included
in event elapsed time but excluded from the adapter's active execution deadline.

Backend source prefix: `novel_to_comic/src/novel_to_comic/`.

| Area | Entry points |
| --- | --- |
| Adapt orchestration | `book_adaptation.produce_book_adaptation` |
| Treatment / blueprint / lettering | `build_narrative_treatment_prompt`, `_generate_blueprint`, `_generate_locked_lettering` |
| Repair | `_repair_source_scope`, `_closed_repair_scope`, `_repair_prompt`, `_generate_book_drafts`, `_splice_draft_repair` |
| Source accounting | `validate_book_adaptation`, `_materialize_draft_ledger`, canonicalization helpers |
| Review | `narrative_review.py`, `adaptation_context`, `review_narrative` |
| Plan | `page_planning.produce_book_plan`, `_produce_book_plan_two_pass`, `_generate_page_map`, `_generate_detail_batch` |
| Caching / scheduling | `generation_checkpoints.py`, `target_artifacts.py`, `paid_shards.py` |
| Transport | `ai/client.py`, `ai/codex_runtime.py`, `ai/anthropic_schema.py` |

Plan already uses checkpointed generation and has map/detail separation with
lettering IDs. Investigate what remains redundant before proposing those as new
features. Likewise, simply raising shard concurrency will not bypass Codex's
serialization and may only inflate queued work.

## Recommended investigation, not an approved design

1. **Reconstruct one attempt end to end without generation.** Build a call graph
   and accounting table from saved records: request purpose, source scope, input
   size, output size, active versus queued time, cache outcome, validation result,
   and why each repair was requested. Separate transport, schema, deterministic
   invariant, narrative-review, and orchestration failures.
2. **Audit the producer/validator/repair contracts together.** Determine whether
   every demanded disposition is representable in the output schema, whether
   constraints contradict one another, and whether local canonicalization or
   splicing can invalidate an otherwise valid model answer. Evaluate shard
   ownership and scene/beat boundaries before changing model instructions.
3. **Measure repair amplification.** A scene concern can expand to a very large
   scope and produce a whole `_BookDraft`. Determine the smallest closed unit of
   change. Compare targeted typed edits against full scoped regeneration; enforce
   provenance and transactional validation either way. Do not pick a patch format
   before understanding deletion, cross-beat references, and ownership semantics.
4. **Audit review scope and consistency.** Identify duplicate full-source/context
   payloads, repeated reviews of unchanged content, and subjective findings treated
   as mandatory repairs. Compare review judgments across captured candidates and
   determine whether feedback is actionable and localized. Preserve the quality
   gate while distinguishing objective failure from editorial preference.
5. **Profile transport separately.** Use the new notification timing to distinguish
   long active reasoning from silent streams or reconnect stalls. Check pinned SDK
   behavior and official documentation before changing stream settings. Consider
   explicit reasoning effort only with evidence and a visible configuration
   contract; do not silently trade away quality or change providers.
6. **Redesign estimates and limits around actual work.** Account for treatment,
   blueprint, lettering, review, schema repair, semantic repair, cache hits, and
   unknown usage. Evaluate bounded per-attempt and cumulative budgets, with an
   intelligible stop reason and preserved progress. A guessed 25% repair margin is
   neither a cost guarantee nor a spend ceiling.
7. **Evaluate candidate designs offline first.** Use the captured cases as a small
   regression corpus, including source loss across boundaries, legitimate
   punctuation, partial repair completion, schema incompatibility, and stalled
   streams. Only then propose a narrow, explicitly authorized live comparison.

The main hypothesis is that oversized/redundant generative work and fragile
repair contracts amplify ordinary model variation into repeated expensive
failures. Several application bugs are established; that broader hypothesis is
not yet proved. Also evaluate simpler explanations rather than making every
failure fit one theory.

## Verification already performed and success criteria

Latest timeout patch: 89 adapter tests passed; 173 related AI-client, image
transport, and Adapt tests passed, with 4 skipped. Documentation reliability
passed. Earlier source-scope fix had a 176-test passing focused run and a replay
of the actual failure. These are separate historical test runs, not an additive
claim of unique tests or end-to-end success. No full adaptation or Plan completion
has been demonstrated after the latest changes.

The next session should deliver a root-cause report with a measured call/cost/time
breakdown, a concrete architecture recommendation, implementation of the chosen
bounded changes, and focused regression tests. Define numerical budgets from the
baseline rather than inventing a target now. Completion should require:

- No provenance loss in replayed cross-boundary repairs; no fabricated ledger links.
- Unchanged successful work is reused, and modified inputs invalidate it correctly.
- Repairs and reviews have explainable scope and bounded amplification.
- Estimates expose uncertainty and cumulative attempts cannot spend indefinitely.
- Transport failures preserve results and clearly distinguish queued, active,
  completed, and indeterminate work.
- Quality evaluation measures narrative fidelity and usable exact lettering,
  not just schema validity or disappearance of error messages.

Do not end by merely recommending another model, raising retries/timeouts again,
or asking the user to run the whole book repeatedly.

# Image Prompt Pipeline Hardening — Master Implementation Plan

Date: 2026-07-10

Status: Ready for implementation

## Purpose

This plan turns the image-prompt review into seventeen ordered, session-sized
implementation slices. Each slice has a standalone brief in this directory and
is intended to be handed to a fresh Codex session after its prerequisites land.
Durable as-built handoffs live under `handoffs/`; they are part of the contract,
not optional chat summaries.

Use one fresh session per slice. Commit or otherwise preserve the completed
slice before starting the next one; use separate PRs when that matches the
project's review workflow. Never ask a session to continue into the next slice.

## Target outcome

At the end of the plan:

- exact active character, location, and prop anchors reach the image model
  verbatim;
- alternate appearances inherit the correct identity or location lineage
  without contradictory canonical clothing, anatomy, weather, damage, or time;
- every selected reference has an explicit role, entity, appearance state,
  authority scope, compatible facets, pose, immutable content snapshot, and
  hash;
- prompt text, reference instructions, upload order, provider bindings,
  dimensions, and controls derive from one compiled request;
- prompt edits cannot retain stale visual briefs, layouts, or overlays that are
  incompatible with a new appearance state;
- replacing a reference at the same path invalidates dependent output;
- the request shown as submitted is byte-equivalent to the request consumed by
  the provider adapter;
- every generated image has reconstructable, redaction-safe provenance;
- deterministic tests and an explicitly authorized visual evaluation measure
  canonical consistency and alternate-state correctness separately.

## Target architecture

```text
Story Bible + PlannedPanel + state-aware user overlay
  -> CanonicalPromptIR
       - protected verbatim anchors
       - editable scene direction
       - generated system constraints
       - active character/location state ids
  -> prompt source fingerprint
  -> ImageModelProfile
  -> ReferencePlan
       - capability-aware final selection
       - role + entity + state + authority facets
       - final order + content hashes
       - dropped candidates + reasons
  -> CompiledGenerationRequest
       - exact prompt sections and final prompt
       - exact per-reference instructions
       - effective target geometry and filtered controls
       - provider-independent compiled request hash
  -> ProviderWireRequest
       - portable, versioned representation
       - no handler-authored semantic prose
       - execution fingerprint
  -> FrozenGenerationRequest
       - immutable request manifest
       - content-addressed reference snapshot locators
       - verified reference hashes
  -> provider transport
  -> image result + provenance record
```

The LLM visual-brief pass becomes a narrow scene-direction writer. It does not
own identity, appearance, location identity, prop identity, reference bindings,
or hard constraints.

Three related hashes have different jobs:

- `compiled_request_sha256` identifies the provider-independent semantic
  request and helps prove deterministic compilation.
- `execution_fingerprint` covers only provider-affecting inputs and immutable
  reference bytes. It drives cache identity and preview/submission parity.
- `provenance_record_hash` covers the complete diagnostic record, including
  dropped candidates and warnings. Diagnostics must not invalidate an otherwise
  identical generation request.

## Sequencing

```text
00 Route truth
  -> 01 Rerender ownership
    -> 02 Canonical prompt IR
      -> 03 Prompt lineage + state-aware overlays
        -> 04 Model capabilities + ReferencePlan
          -> 05 Compiled generation request
            -> 06 Prompt hygiene + geometry
              -> 07 Provider wire + transport
                -> 08 State-asset lifecycle
                  -> 09 Conditioned state assets
                    -> 10 Frozen request submission
                      -> 11 Panel caller convergence
                        -> 12 Non-panel provenance
                          -> 13 Exact preview
                            -> 14 Golden corpus + CI gates
                              -> 15 Visual evaluation
                                -> 16 Rollout + legacy removal
```

| Slice | Brief | Primary contract produced |
|---|---|---|
| 00 | [Route truth and characterization](00-route-truth.md) | Alias/model decisions and override precedence are truthful. |
| 01 | [Rerender safety](01-rerender-safety.md) | Authoritative edits cannot leave stale derived prompt state. |
| 02 | [Canonical prompt IR](02-canonical-prompt-ir.md) | Anchors, scene direction, and constraints have separate owners. |
| 03 | [Prompt lineage](03-prompt-lineage.md) | Upstream and state changes rebuild canonical data without unsafe overlays. |
| 04 | [Model capabilities and ReferencePlan](04-model-capabilities-and-reference-plan.md) | One final, capability-aware, state-safe reference selection exists. |
| 05 | [Compiled generation request](05-compiled-generation-request.md) | Exact prompt/reference semantics form one provider-independent request. |
| 06 | [Prompt hygiene and geometry](06-prompt-hygiene-and-geometry.md) | Prompts are compact, text-safe, budgeted, and dimensionally truthful. |
| 07 | [Provider wire and transport](07-provider-wire-and-transport.md) | Isolated handlers serialize the exact compiled request without reinterpretation. |
| 08 | [State-asset lifecycle](08-state-asset-lifecycle.md) | Alternate assets have non-conflicting prompts, scoped corrections, and stale-lineage detection. |
| 09 | [Conditioned state assets](09-conditioned-state-assets.md) | Character/location states derive from compatible canonical identity through the shared request path. |
| 10 | [Frozen request submission](10-frozen-request-submission.md) | Queued work consumes immutable request data and reference bytes. |
| 11 | [Panel caller convergence](11-panel-callers-and-provenance.md) | Draw, rerender, estimate, and Labs panel paths share one request and provenance contract. |
| 12 | [Non-panel provenance](12-non-panel-callers-and-provenance.md) | Style, cast, location, state, and prop images use the common provenance envelope. |
| 13 | [Exact preview](13-exact-preview.md) | Dev Content shows the prepared/submitted request without hidden paid work. |
| 14 | [Golden corpus and CI gates](14-golden-corpus-and-ci-gates.md) | Deterministic scenarios prevent architectural and semantic regressions. |
| 15 | [Visual evaluation](15-visual-evaluation.md) | Authorized paired evidence measures canonical and alternate-state quality. |
| 16 | [Rollout and legacy removal](16-rollout-and-legacy-removal.md) | Evidence gates final cutover, cleanup, documentation, and verification. |

## Global invariants

Every slice must preserve these:

1. `visual_anchor` text is immutable source material. Never paraphrase,
   summarize, shorten, translate, sanitize, or silently filter it in a
   generator-bound prompt.
2. Text remains a Stage 9 concern. Generated panel art contains no lettering,
   caption boxes, speech bubbles, labels, signs, or SFX text. If a protected
   anchor conflicts with this policy, report the conflict for upstream
   correction; never mutate the anchor in the compiler.
3. Backend stage boundaries remain unchanged. The four UI stations are
   presentation only.
4. Model names and capability decisions stay out of prompt templates.
5. Aspect/dimension math remains in `panel_aspect.py`.
6. An active appearance/location state wins over canonical mutable facts.
   Preserve only canonical facets not contradicted by the active state.
7. Visible subjects are generation requirements, not optional reference slots.
   If a route cannot represent all required subjects under its hard cap, fail
   clearly or proceed under an explicitly tested text-only policy; never
   silently omit a subject identity.
8. Reference ordering has exactly one owner. Prompt indices and uploaded bytes
   derive from the same final plan.
9. User-authored corrections are overlays, not mutations of canonical anchors
   or generated invariants. State-sensitive overlays are dropped with a warning
   when their target state becomes incompatible.
10. Provider adapters and isolated handlers serialize; they do not add semantic
    prompt prose, choose references, reorder inputs, or apply a second cap.
11. Provider fallback must not silently switch model families. Availability
    fallback is outside this plan.
12. Existing user changes in the worktree are preserved.

Style proofs are not required to invent panel anchors. When a style proof uses a
specific character, location, or prop anchor, that supplied anchor follows the
same verbatim rule. Abstract style proofs with no entity anchor are exempt.

## Fresh-session protocol

For every session:

1. Read repository `AGENTS.md`, this README, the assigned brief, and only the
   source/test files named by that brief or discovered through targeted tracing.
2. For every slice after 00, read `handoffs/<previous-slice>.md` and verify its
   delivered contract/exit criteria on the current branch. If the durable
   handoff or prerequisite contract is missing, stop and report the dependency
   instead of inventing a local substitute.
3. Add the focused failing regression first, then implement the smallest
   production change that satisfies it.
4. Do not refactor unrelated code or begin the next slice.
5. Do not add a compatibility shim unless the user asks; breaking internal
   prompt JSON/model changes are acceptable in this project.
6. Run focused tests plus the normal checks required by the brief.
7. Use an independent verifier for non-trivial implementation. Use a security
   reviewer when auth, secrets, signed asset access, storage permissions, or
   untrusted provider data changes.
8. Before the final response, write `handoffs/NN.md` using
   [`handoffs/README.md`](handoffs/README.md). It must record files changed,
   contracts/schema versions, tests/results, deviations, verifier/security
   outcomes, unresolved risks, and a commit hash only if a commit exists. A
   chat-only handoff does not satisfy the slice.

Copy/paste kickoff for a new session:

```text
Implement only Slice NN from
docs/superpowers/plans/2026-07-10-image-prompt-hardening/<slice-file>.md.
First read AGENTS.md, the plan README, the full slice brief, and (unless this is
Slice 00) handoffs/<previous-slice>.md. Verify the prior slice's exit criteria,
use tests first, preserve unrelated worktree changes, do not make paid model
calls without the explicit authorization allowed by the assigned brief, and do
not start the next slice. Before replying, write handoffs/NN.md using the handoff
template.
```

## Standard verification commands

Run from the repository root, substituting focused tests as needed:

```bash
rtk uv run --directory novel_to_comic pytest -q tests/<focused-test>.py
rtk uv run --directory novel_to_comic pytest -q
rtk uv run --directory novel_to_comic ruff check src tests
```

When frontend code is touched:

```bash
rtk npm --prefix web test
rtk npm --prefix web run lint
rtk npm --prefix web run build
```

Do not make paid prompt/image model calls unless Slice 15 is reached and the
user explicitly authorizes credit usage after seeing an estimate.

## Final acceptance criteria

- A long sentinel anchor for every active character, location, and prop appears
  byte-for-byte in the final provider-bound request.
- Base, minor alternate-outfit, significant anatomy-change, restored-state,
  location-time, weather, and damage fixtures select compatible authority
  facets and references.
- A canonical reroll marks dependent state assets stale until they are
  regenerated from the new canonical bytes.
- Changing selected reference bytes at the same path changes execution identity
  and invalidates dependent art; changing an unselected diagnostic candidate
  does not.
- Prepared manual edit, instructed edit, draw, rerender, submitted preview, and
  matching Labs scenarios compile the same execution fingerprint for the same
  inputs. A provisional estimate shares route profile, ReferencePlan, geometry,
  and pricing inputs but does not claim an exact fingerprint.
- Narration, continuity, no-lettering, one-body, single-instant, crop, and
  appearance locks each have one owner.
- Reference-policy tests cover 0–4 visible subjects plus location, style, prop,
  and continuity candidates for every production route.
- Provider-wire snapshots prove exact prompt text, reference instructions,
  order, dimensions, aspect, and supported controls.
- The submitted Dev Content preview is byte-equivalent to frozen request
  provenance and provider-adapter input.
- Configured/expected model identity is distinguished from the provider-reported
  actual model identity.

## Explicit deferrals

These findings should not expand the core slices:

- automatic cross-model failover;
- reference embeddings or face-recognition gates;
- additional previous-panel continuity beyond intentional match cuts;
- runtime capability discovery from LiteLLM;
- broad GPT-specific work while no production alias routes to GPT Image 2;
- Reve v2 feature work beyond a correct request contract while its layout
  endpoint remains disabled by default;
- generalized world-state timelines;
- provider retry normalization and binary image validation, which deserve
  separate reliability plans after the prompt contract is stable.

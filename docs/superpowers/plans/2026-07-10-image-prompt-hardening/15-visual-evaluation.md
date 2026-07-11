# Slice 15 — Visual Consistency Evaluation and Authorized A/B

## Fresh-session assignment

Implement only this slice. Read `AGENTS.md`, the sibling `README.md`, this file,
and verify every Slice 14 deterministic release blocker passes. Do not begin
Slice 16.

Do not call a paid prompt/image/evaluator model until the user has approved a
written experiment plan and credit estimate in this session.

## Goal

Measure whether the new request pipeline preserves canonical identity/location
quality while improving alternate-appearance correctness. Keep character,
location, style, composition, props, and unwanted text as separate outcomes.

## Required reading

- Slice 14 corpus handoff and all current deterministic gate results
- `novel_to_comic/src/novel_to_comic/labs/`
- `novel_to_comic/src/novel_to_comic/server/routers/labs.py`
- existing visual-consistency evaluator models, reports, and UI
- credit estimate/reservation code for Labs and image generation
- previously generated baseline artifacts/provenance that can be reused without
  spending credits

## Deliverables

1. Define a versioned `VisualEvaluationRecord` with attributable scores/evidence
   for:
   - character identity consistency per visible character;
   - appearance-state correctness separately from identity;
   - location identity and location-state correctness;
   - recurring prop identity where expected;
   - selected style consistency;
   - composition/layout adherence;
   - missing, merged, duplicated, or extra subjects;
   - unwanted readable text;
   - scenario id, route, compiler/wire versions, execution fingerprint, selected
     refs/dropped reasons, cost, and latency.
2. Version any model-evaluator rubric and retain structured evidence needed to
   audit its score. Supplement with blinded human review for ambiguous identity
   or state judgments. Model evaluation does not replace deterministic CI gates.
3. Add a Labs experiment record that can compare retained baseline artifacts
   with new frozen requests. Capture paired scenario identity, route, all request
   provenance, evaluator results, reviewer notes, cost, and latency.
4. Keep comparison isolated to Labs. Do not add a permanent production
   old/new-compiler toggle. Prefer already-saved old artifacts; if an old request
   must be regenerated, label that additional spend explicitly.
5. Before any paid call, present:
   - selected scenario subset and routes;
   - number of prompt, image, and evaluator calls;
   - estimated credits/cost range;
   - intended sample size/repeats and provider nondeterminism limits;
   - decision rule and stopping condition.
   Wait for explicit authorization.
6. Use a balanced paired sample spanning canonical, minor-state, significant
   state, restored state, location state, constrained refs, prop, and multi-
   subject cases. Use seed/control settings only where the provider genuinely
   supports them; never imply deterministic image equality.
7. Analyze by route and failure class, not only an aggregate score. Report sample
   size and uncertainty. Do not claim broad improvement from a handful of images.
8. Establish the final visual acceptance decision from paired evidence:
   - no material regression in canonical character identity, location identity,
     style, subject completeness, or unwanted text;
   - clear improvement in alternate character/location state correctness;
   - no new route-specific systematic failure.
   Define “material” numerically before running the experiment, using baseline
   variance and the chosen rubric.
9. Produce a reviewable report linked to scenario/request/result provenance.
   If credits are not authorized, deliver the complete harness and experiment
   proposal, mark visual evidence pending, and do not claim rollout readiness.

## Tests first

- Evaluator records require scenario, route, request identity, and per-dimension
  results; aggregate-only output is rejected.
- Per-character scores cannot be accidentally assigned by subject index after
  ordering changes.
- Appearance-state correctness and canonical identity are distinct fields.
- Location identity/state, prop, composition, subject errors, and text incidence
  remain separate.
- Baseline/new pairing rejects mismatched scenario or route metadata.
- Rubric version and structured evidence are retained.
- Cost-estimate dry run performs no paid calls.
- Labs-only comparison cannot select a legacy compiler in production routes.
- Report calculations handle missing/failed generations without silently
  excluding them.

## Exit criteria

- The evaluation harness is attributable, versioned, and test-covered.
- A paid experiment was either explicitly authorized and completed, or clearly
  remains pending with no credits spent.
- When run, results are paired, route-aware, uncertainty-aware, and separated by
  consistency dimension.
- No deterministic Slice 14 gate regresses.
- Focused tests, full backend tests, Ruff, and affected Labs tests pass.

## Handoff to Slice 16

Write `handoffs/15.md` using the durable handoff template before replying.

Report rubric/evaluator schema, Labs experiment contract, authorization and
credit estimate, scenarios/routes/sample size, complete results or pending
status, decision thresholds, failure analysis, and report location. Slice 16
must not declare final rollout complete without passing visual evidence or an
explicit user-approved waiver.

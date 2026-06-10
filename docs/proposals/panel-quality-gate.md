# Proposal: Automated Panel Quality Gate

**Status:** proposed (deep-dive pending)
**Origin:** pipeline review, June 2026 — finding #7 ("missing feedback loop: no automated panel QA")

## Problem

The pipeline validates everything *up to* the image and almost nothing *about*
the image.

What exists today:

- **Aspect validation** — `_meta_with_output_aspect` / `_raise_if_aspect_mismatch`
  in `stages/s7_draw.py` flag a returned image whose frame shape disagrees with
  the requested generation aspect (`shape_mismatch` failure classification).
- **Failure metadata** — provider errors and blocks are classified
  (`provider_blocked` / `shape_mismatch` / `generation_error`) and written to
  `draw/<scene>/panel_NNN.png.failure.json` with a recovery hint.
- **Human review surfaces** — `server/panel_acceptance.py` (accept/reject),
  `panel_versions.py` (version history on regenerate), per-panel Quick Re-Do,
  and the stage-level approve gate.

What does not exist: any check that a *successfully generated* image actually
satisfies its prompt. The structured `ImagePrompt` states, precisely and
machine-readably, what the panel must contain — `subjects` (count, identity,
action, expression), `key_objects`, `visual_requirements`, `constraints`
("exactly N characters", "no lettering", "single frozen instant"),
`has_narration_caption` + `preferred_caption_zone` (negative space
requirement). None of it is verified. The current workflow is "human eyeballs
every panel," which:

1. does not scale past a short story (a novel produces 300–600 panels);
2. makes per-book cost unpredictable for the SaaS direction (manual redos are
   the variable cost); and
3. wastes the richest QA signal we have — the prompt itself is the rubric.

## Known failure modes the gate should catch

Observed/expected failure classes, roughly ordered by frequency × severity:

| # | Failure | Why it happens | Detectable from |
|---|---------|----------------|-----------------|
| 1 | Rendered text/lettering in the art | image models love drawing captions; lettering is composed in Stage 8, so baked-in text collides with real bubbles | constraints ("no lettering") |
| 2 | Wrong character count (duplicate figure, missing character, extra bystander) | multi-subject prompts + ref blending | constraints ("exactly N characters") |
| 3 | Identity drift (character doesn't match their ref/anchor) | weak ref conditioning, style overpowering identity | subjects[].identity + ref image |
| 4 | Missing must-show object (the prop the beat is about) | prompt bloat, model attention | key_objects / visual_requirements |
| 5 | Multi-moment image (before/after, motion sequence, split panel) | action beats with sequential phrasing | constraints ("single frozen instant") |
| 6 | No negative space where a narration caption will land | caption-space directive ignored | has_narration_caption + preferred_caption_zone |
| 7 | Sub-panel grids / internal borders | ref sheets leaking grid layout | layout constraint line |
| 8 | Wrong location state (pre-collapse furniture in a post-collapse panel) | anchor contamination (mostly fixed structurally; residual model error) | location_state_id + setting |

## Proposed approach

### Shape: a `qa` pass between draw and compose

A cheap **vision-model scoring pass** that runs per panel after generation,
writes its verdict into the existing asset-meta sidecar, and feeds the
existing regeneration machinery. Explicitly *not* a new blocking pipeline
stage by default — it is an annotator that turns "review all panels" into
"review the flagged ones."

```
draw → [panel_qa annotates] → human reviews flagged panels → compose
```

### Mechanics

1. **Rubric generation (deterministic, no LLM).** For each panel, derive a
   checklist from the stored `ImagePrompt`:
   - `character_count == N` (from constraints)
   - `no_rendered_text`
   - one item per `key_object` and per `visual_requirement` (cap ~6, highest
     priority first — same prioritization as the prompt assembler)
   - `single_instant`
   - `caption_space_<zone>` when `has_narration_caption`
   - `single_unified_scene` (no sub-panels)

2. **One vision call per panel.** Send the generated PNG + the rubric to a
   cheap vision model (via the existing LiteLLM gateway; `effective_prompt_model`
   tier or a dedicated `qa_model` config key). Ask for strict JSON:
   `{check_id: {pass: bool, confidence: 0-1, note: str}}` plus an overall
   0–100 score. Temperature 0. This mirrors the existing
   `generate_visual_brief` pattern (never raises; absent result = no verdict).

3. **Identity check (phase 2, optional).** For panels with subjects, a second
   variant of the call includes the character's `front.png` pose crop and asks
   "is this the same character?" — this is the only check that needs a second
   image input, so keep it behind its own config flag.

4. **Verdict storage.** Extend the existing meta sidecar
   (`artifacts.write_asset_meta`) with a `quality` block:

   ```json
   "quality": {
     "version": 1,
     "model": "...",
     "score": 78,
     "checks": {"no_rendered_text": {"pass": false, "confidence": 0.93, "note": "caption box bottom-left"}},
     "verdict": "flagged",          // pass | flagged | failed
     "checked_prompt_sha256": "..." // invalidates verdict when prompt changes
   }
   ```

   Storing inside the meta sidecar (not a new file) means the existing
   `asset_matches_meta` idempotency and the failure-file conventions stay
   untouched; `checked_prompt_sha256` makes the verdict self-invalidating.

5. **Routing the verdict.**
   - `failed` (hard check failed with high confidence — rendered text, wrong
     character count) → set `regeneration_status="recommended"` on the planned
     panel (the field and its UI affordances already exist in
     `models/layout_plan.py` / LabsRoom), and surface the note in the panels
     list (`server/routers/stages.list_images` already returns failure
     metadata; add the quality block the same way).
   - `flagged` (soft check failed or low confidence) → no status change, but
     visible in the review UI as a yellow chip with the note.
   - `pass` → green; reviewer can skip.
   - **Auto-redo loop (phase 3, off by default):** for `failed` panels, one
     automatic regeneration with the failed checks appended to the prompt as
     corrective constraints, then re-score; never more than one auto-attempt,
     and always within the existing cost-limit accounting.

### Where it hooks in

- `stages/s7_draw.py::_generate_panel` — after `_write_generation_meta`, fire
  the QA call (same semaphore family, separate concurrency knob). Keeping it
  inside draw means regenerations and Quick Re-Do get scored for free.
- Alternatively (cleaner separation, slightly more plumbing): a sibling module
  `panel_qa.py` invoked from draw and from `regenerate_panel_image`, so the
  scoring logic is unit-testable without the generation path.
- `server/panel_acceptance.py` — accepting a panel overrides any verdict
  (human wins, always).

### Config

```yaml
panel_qa:
  enabled: true          # default on once stable; start opt-in
  model: null            # default: effective_prompt_model() vision tier
  identity_check: false  # phase 2
  auto_redo: false       # phase 3
  flag_threshold: 0.7    # min confidence to flag
```

### Cost envelope

One vision call ≈ image input (~1–2k tokens at low detail) + ~300 output
tokens. On a cheap vision tier this is one to two orders of magnitude below
the image generation cost it protects, and it *replaces* far more expensive
manual-redo credits. Estimate should be folded into the draw stage's
`estimate_cost` when enabled.

### Evaluation plan (before trusting it)

1. Label ~100 panels from past projects (pass/fail per check) by hand.
2. Run the scorer; measure per-check precision/recall. Gate on **precision**
   for `failed` verdicts (false "failed" wastes a regeneration; false "pass"
   just falls back to today's status quo).
3. Tune `flag_threshold` so flagged-rate lands near the actual defect rate
   (expected 10–20% of panels).
4. Only after that, consider enabling `auto_redo`.

### Non-goals

- Aesthetic scoring ("is this beautiful") — too subjective, low agreement.
- Style-consistency scoring across panels — real problem, but needs a
  different mechanism (embedding similarity vs. the style sample), separate
  proposal.
- Blocking the pipeline on QA verdicts — the gate annotates and recommends;
  the stage-approve flow remains the only hard gate.

### Sequencing

| Phase | Scope | Effort |
|-------|-------|--------|
| 1 | rubric builder + single vision call + quality block in meta + chips in panels list | ~2–3 days |
| 2 | identity check with pose-crop comparison | ~1 day |
| 3 | auto-redo loop with corrective constraints | ~1–2 days, gated on eval results |

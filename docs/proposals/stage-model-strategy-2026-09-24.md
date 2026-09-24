# Stage model strategy — September 24, 2026

Status: Proposed. This is research plus recommendations. It builds on the
[Sept 9 text research](text-model-research-2026-09-09.md) and the
[Sept 11 selection overhaul](model-selection-overhaul-2026-09-11.md) and does not
repeat them. No routing changes were made and no paid calls were run. The only
measured token numbers come from the
[Sept 13 Adapt evidence](../reviews/2026-09-13-adapt-plan-evidence.json) and the
[Sunburst cost note](../research/2026-09-22-sunburst-provider-costs.md). Every other
volume is labelled **modeled**.

## Summary

1. **Canary's architecture already matches published best practice.** Recent
   novel→screenplay and story→manga research gets its gains from breaking the work
   into steps with explicit intermediate artifacts: causal plot structure, outlines,
   layout as its own variable, a per-section entity memory, and editable lettering.
   Canary already does all of this: treatment → blueprint → lettering → ledger →
   review/repair, then Plan map → detail, Cast as entity memory, and hybrid
   lettering. More gains will come from measurement, caching and review volume,
   not from a stronger model.
2. **For your product, text generation is about as expensive as images.** One
   measured Adapt attempt on *Call of Cthulhu* (45 pages) used about 482K input and
   104K output tokens. That is **~$2.00 on Sol (≈$0.044/page)**. Draw costs about
   $0.054–0.077 per page. The Fable run on the same book cost ~$11 (≈$0.24/page),
   more than three times the cost of drawing the pages.
3. **Immediate hygiene:**
   - Replace the `claude-opus-5` route with **Opus 5.5**, which is now legacy-free,
     cheaper ($4/$20 vs $5/$25) and ranked higher.
   - Don't offer Fable 5.1 or Astra as default Adapt choices. On Cthulhu they cost
     5× Sol, and they refused on 4 of 19 events.
   - Replace Luna for **visual review**. It is the cheapest model you have, and
     visual review is the one job here that depends on fine-grained perception.
4. **Pick models by *cost per accepted page*, not token price.** Use a fixed
   fixture set, a cheap transport/refusal gate, stage-owned validators as automatic
   metrics, and blind pairwise review for creative quality. The method is below.

## What the current setup is

| Stage | Calls (features) | Default model | Effort | Evidence |
|---|---|---|---|---|
| Extract | per-section `extract.story_bible` (16K-char chunks) + `extract.narrative_arcs` | GPT-6 Luna | gateway `low` | modeled |
| Brief | `brief.infer` | Luna | low | modeled |
| Style/Cast text | suggestions, sample brief, instruction rewrites, `cast.design` | Luna | low | modeled |
| Adapt | treatment → 3 blueprints → 3 lettering → validation → 3 reviews → repairs → re-review | GPT-6 Sol | low | **measured** |
| Plan | `plan.map` → parallel `plan.detail` → `plan.book` review | Sol | low | unmeasured |
| Draw | complete page, GPT Image 2.5 Sunburst via FAL | fixed edition profile | — | **measured** |
| OCR | `draw.page_ocr` | Luna | low | modeled |
| Visual review | `draw.visual_review`, `cast.visual_review` | Luna (`GATEWAY_PAGE_OCR`) | low | modeled |

Observations from the code:

- **Reasoning effort is set per gateway route, not per stage.** Sol runs at `low`
  for both Adapt and Plan ([litellm/config.yaml](../../litellm/config.yaml)). Effort
  is probably the cheapest quality knob you have, but right now it can't be tuned
  for one stage alone.
- **No explicit prompt caching.** [ai/client.py](../../novel_to_comic/src/novel_to_comic/ai/client.py)
  reads `cached_tokens`, but nothing sets Anthropic `cache_control`. Reviews use
  **57% of Adapt input tokens** but only 15% of output. The three blueprint,
  lettering and review calls share large prefixes. Cached reads are 90% off on
  GPT-6 and 95% off on Opus 5.5, but only when the shared content comes first
  in the prompt and is byte-identical.
- **Measured Adapt per-call shapes** (Sept 13 evidence): treatment ≈ 26–40K in /
  1.3–4.8K out, blueprint ≈ 14–18K / 4–8K, lettering ≈ 16–33K / 4–18K, review ≈
  41–46K / 1.4–2.6K. One full GLM attempt took 12m 53s of wall time.
- **Measured refusals and failures on Cthulhu:** Fable had 3 refusals and 4
  transport failures in 13 events; Astra had 1 refusal and 2 transport failures in
  6. Sol, GLM-5.3-Flash and Gemini 3.8 Flash had no refusals.

## What the research says (and what it means for Canary)

**Decomposition beats direct generation.**
- DSR splits creative narrative work from format conversion. Professional
  screenwriters preferred it over Gemini 2.5 Pro 75% of the time.
- R² extracts a causal plot graph with a sliding-window reader, then applies
  hallucination-aware refinement. It won 22–57% more pairwise comparisons against
  earlier methods.
- MangaFlow treats layout as an explicit, editable intermediate, keeps a
  story-section memory for character/scene/object references, and places text as
  a separate step. It reports better layout adherence and cross-panel consistency
  than direct generation.

Canary's `causal_spine`/`essential_event_ids`, blueprints, ledger, Plan and hybrid
lettering are all instances of these ideas. So don't collapse stages to save
calls. The research consistently finds that single-pass generation is worse.

**Advertised context is not the same as effective context.**
- "Context rot" research shows degradation well before the window is full.
- Facts in the middle of the input are recalled noticeably worse than facts at
  the start or end.
- The best 1M-token retrieval scores (MRCR 8-needle) are ~74–76%, and several
  frontier models score far lower.

For Canary:
- Keep Extract chunked. At 16K characters (~4K tokens), each chunk is well inside
  the reliable zone.
- Give Adapt/Plan structured digests plus the specific source units they need,
  not the whole book.
- Put stable content first (this also enables caching) and the task instruction
  last.

**Schema validity is not semantic correctness.** Benchmarks show near-perfect
JSON/schema pass rates, but field-level value accuracy of only ~80–83%. Canary's
stage-owned validation (ADR 0014) is the right defense. Measure **first-try
semantic validation pass rate and repairs per stage**, not parse rate.

**Creative-writing leaderboards disagree.**
- EQ-Bench Creative Writing v3 (Sept 2026): Opus 5 (2121 Elo) > Kimi K3 (2071) >
  GPT-5.6 Sol (1963).
- Vulsar's benchmark puts GPT-6 Astra first and Opus 5 and Kimi K3 in the 50–65%
  range.
- Opus 5.5 and GPT-6 Sol/Luna shipped on Sept 22 and aren't well covered yet.

Treat benchmarks as a way to choose which models to test, never as the
decision.

**LLM judges are usable if you debias them.** Swap A/B order and average, use a
judge from a different model family than either candidate, and hide model names.
Self-preference largely disappears once style confounds are controlled.

## Model landscape, September 24, 2026

USD per million tokens, standard uncached rates. Verify in the account before
spending.

| Model | In / Out | Cached read | Notes |
|---|---:|---:|---|
| GPT-6 Astra | $10 / $50 | $1.00 | top tier; no `none` effort |
| GPT-6 Sol | $2 / $10 | $0.20 | released Sept 22; effort `none`…max |
| GPT-6 Luna | $0.10 / $0.50 | $0.01 | released Sept 22; cheapest capable model on the market |
| Claude Opus 5.5 | $4 / $20 | $0.20 | released Sept 22; #1 on the AA Intelligence Index; default effort `medium`; batch half price |
| Claude Opus 5 | $5 / $25 | $0.50 | **legacy**; strictly dominated by 5.5 |
| Claude Fable 5.1 | $10 / $50 | $0.25 | heavy reasoning; refused on Cthulhu |
| Claude Sonnet 5 | $2 / $10 | $0.20 | Sol-priced Anthropic comparator |
| Gemini 3.8 Flash | $0.75 / $3.75 | $0.075 | **doubles to $1.50/$7.50 on Jan 1, 2027** |
| Kimi K3 | $3 / $15 | $0.30 | #2 on EQ-Bench creative writing |
| DeepSeek V4.1 Flash | $0.15 / $0.60 off-peak ($0.30 / $1.20 peak) | $0.003 | MIT; vision; peak/off-peak pricing |
| MiMo V2.6 Pro | $0.435 / $0.87 (OpenRouter) | — | MIT; top open-weight model on the AA index |
| GLM-5.3-Flash | $0.15 / $0.50 | — | measured Adapt attempt $0.12, but that attempt failed review |

What one measured Adapt attempt (482K in / 104K out, no caching) would cost on
each model:

| Model | Cost | Per page (45) |
|---|---:|---:|
| Luna | $0.10 | $0.002 |
| DeepSeek V4.1 Flash (off-peak) | $0.13 | $0.003 |
| MiMo V2.6 Pro | $0.30 | $0.007 |
| Gemini 3.8 Flash | $0.75 (→ $1.50 in 2027) | $0.017 |
| **Sol / Sonnet 5** | **$2.00** | **$0.044** |
| Kimi K3 | $3.01 | $0.067 |
| Opus 5.5 | $4.01 | $0.089 |
| Fable 5.1 / Astra | $10.02 | $0.22 |

This is arithmetic from list prices. Reasoning tokens are counted as output, and
repair rounds add 30–60% (the measured GLM repair plus re-review was 40% of that
attempt).

## Stage by stage: needed strengths, recommendation, budget

Budgets are **provider USD per drawn page, all attempts included**. The reference
point is Draw at $0.054–0.077/page. A healthy rule is that **all text work
combined should cost no more than one Draw page per page**. At a 2× credit markup,
that keeps text below roughly a quarter of what the user pays.

### Extract: faithful reading at scale

Strengths needed, in priority order:
1. **Literal fidelity and low hallucination.** It must record only what the text
   supports and copy visual anchors verbatim.
2. **Entity/coreference tracking across chunks,** so late-book appearance states
   are caught.
3. **Nested-schema discipline.**
4. **Low over-refusal on dark fiction.** Extract reads everything first, so a
   refusal here blocks the whole book.
5. **Multilingual reading** (e.g. Kafka in Spanish).

Not needed: prose quality or deep reasoning.

**Default:** Luna. Evaluate `low` vs `medium` effort. **Challengers:** DeepSeek
V4.1 Flash, Gemini 3.8 Flash. Escalate to Sol only on measured recall misses.

**Budget:** modeled at ~3–4× source tokens in and ~1–2× out. That is about
$0.02–0.03 for Cthulhu and ~$0.15 for a 100K-token novel on Luna.
**Target ≤ $0.003/page.** Sol would be ~20× this.

### Brief and Style/Cast text: bounded rewriting

Strengths: follow requested changes exactly, preserve anchors verbatim, and don't
invent entities or embellish.

**Default:** Luna. There is no case for spending more; errors here are cheap to
see and fix at the checkpoints. **Budget: ≤ $0.01 per book.**

### Adapt: the creative core, where spending is justified

Strengths needed, in priority order:
1. **Narrative judgment:** compression, choosing essential events, pacing,
   reveals, emotional turns.
2. **Dialogue voice and economy:** lettering has hard word budgets, in every
   target language.
3. **Faithful accounting:** every source unit gets a disposition, IDs are cited
   correctly, and authored order is preserved.
4. **Large nested structured output** (up to ~18K tokens per call).
5. **Low over-refusal on literature** that contains violence, horror or
   profanity. This is a product-level metric, not an edge case.
6. **Stream stability** under the 900 s deadline.

The review and re-review calls are a *checking* task. They are 57% of input
tokens and need comprehension and precision, not voice. That justifies measuring
a cheaper review model separately, while the authoring calls stay on the chosen
creative model.

**Default:** Sol. Test `medium` effort against the current `low`.
- **Premium tier:** Opus 5.5 at `medium`.
- **Challenger:** Kimi K3, after the schema and refusal gates.
- **Drop:** the Opus 5 route. Hide Fable/Astra unless blind review shows a win
  that justifies the 5× cost.

**Budget:**
- **Target ≤ $0.06/page** on the default tier, including one repair round.
- **Premium ≤ $0.12/page.**
- **Enforce a stage ceiling at 2× the estimate.** The Fable run overran its
  $7.26 estimate by 40% and exhausted the Anthropic balance.

### Plan: spatial and referential precision

Strengths needed:
1. **Drawability reasoning:** what fits a panel and what a single image can show.
2. **Strict ID discipline:** each visible entity maps to a valid state ID, and a
   hallucinated ID is a hard failure.
3. **Capacity arithmetic** for lettering per panel/page.
4. **Consistency across parallel detail batches.**
5. **Enum and schema adherence.**

Prose quality is irrelevant. Moderate reasoning helps; the client already warns
when reasoning is ≥25% of output.

**Default:** Sol. **Trial:** Luna at `medium`, run on *frozen accepted Adapt
artifacts* so that only planning quality varies. **Challenger:** Sonnet 5.

**Budget:** unmeasured, so instrument it first. **Target ≤ $0.03/page** on Sol, or
≤ $0.005/page if Luna passes.

### OCR: literal transcription

Strengths: read stylized lettering literally, keep accents and punctuation, never
"auto-correct" toward the expected text, and return usable boxes.

**Default:** Luna. The GLM-OCR / GLM-4.6V comparison from the Sept 9 doc still
applies. **Metric:** missed lettering defects and false redraw triggers, not
character error rate alone. **Budget ≤ $0.002/page.**

### Visual review: the stage most likely to be under-provisioned

Strengths needed:
- Comparing several images (the page plus up to 8 references).
- Fine-grained identity and costume/state perception.
- **Calibrated** judgment: a false positive costs a ~$0.06 redraw, and a false
  negative ships a defect.

The cheapest model is the wrong default for this job.

**Candidates:** Gemini 3.8 Flash (strong vision, ≈ $0.015/page), then Sol
(≈ $0.04/page, modeled at ~12K image+text in / 1.5K out). Keep review
by-exception (ADR 0015) so it isn't run on every page.

**Budget ≤ $0.015/page averaged over all pages.**

### Budget roll-up (45-page book, default tier)

| Work | Modeled / measured $ | Per page |
|---|---:|---:|
| Extract + Brief + Style/Cast text (Luna) | ~$0.05 | $0.001 |
| Adapt (Sol, 1 attempt + repair) | ~$2.6–3.2 | $0.06–0.07 |
| Plan (Sol) | ~$1.0–1.4 (unmeasured) | ~$0.03 |
| OCR + visual review | ~$0.3–0.7 | ~$0.01 |
| **Text subtotal** | **~$4–5** | **~$0.10** |
| Draw first pass (measured) | ~$2.4–3.5 | $0.054–0.077 |
| Style/cast images, cover | ~$0.6–1.0 | ~$0.02 |

Text is currently **above** the "≤ one Draw page" rule. The main levers, in
order:
1. Caching the review prefixes.
2. Leaner review payloads.
3. Plan on Luna, if it passes.
4. Effort tuning.

## How to pick provider and model

**North-star metric:** *cost per accepted page* = provider USD for the whole book
(including failures, refusals, repairs, and redraws traced to upstream defects)
÷ pages accepted at the Draw checkpoint. Pair it with quality gates. Price per
token is only an input to this number.

1. **Fixture set** (already in `projects/`, plus a held-out set you never tune
   prompts against):
   - *The Egg* (short)
   - *The Terror* (dark, short)
   - *Lady or the Tiger*
   - *Call of Cthulhu* (horror, medium)
   - *Dungeon Crawler Carl* (dialogue, profanity)
   - Kafka *La metamorfosis* (Spanish, long)
   - *The Flowers* (the refusal regression case)
2. **Gate 0: transport/schema probe** (a few cents per model).
   - Nested Pydantic schema acceptance, enums, refusal fields.
   - Streaming under the 900 s deadline.
   - Reasoning and cached-token accounting.
   - Image limits for the vision stages.
3. **Gate 1: refusal probe.** Run the exact Extract and Adapt requests for the
   dark fixtures. Any refusal on a fixture is disqualifying for a default slot.
4. **Gate 2: automatic stage metrics** from the validators you already have.
   Freeze upstream artifacts and vary one stage at a time.
   - First-try validation pass rate and repairs per book.
   - Ledger coverage and invalid ID count.
   - Lettering capacity violations.
   - Extract recall of late-book states against a hand-checked list.
   - OCR missed defects.
5. **Gate 3: blind pairwise review** for Adapt, and for Plan via the drawn
   result.
   - A human judges; a cross-family LLM judge with swapped order pre-screens.
   - Promote on a ≥60% win rate with no gate regressions, *or* parity plus ≥30%
     lower cost per accepted page.
6. **Record everything per call:** provider, endpoint, model, effort, transport,
   input/cached/output/reasoning tokens, latency p50/p95, refusal and failure
   class. Most of this already exists in usage events. Add effort and cache hits.
7. **Re-run on release cadence.** GPT-6 Sol/Luna, Opus 5.5 and MiMo V2.6 all
   shipped within a single week. Budget a quarterly re-qualification, plus one
   whenever a candidate model is released.

The existing mock/replay mode keeps Gates 2–3 cheap after the first paid run:
replay frozen upstream artifacts and pay only for the stage under test.

## Product health (provider strategy)

- **Concentration risk.** Every default text stage and Draw depend on OpenAI (Draw
  through FAL). Keep **one qualified alternative per stage** (for example Opus 5.5
  for Adapt, Gemini 3.8 Flash for Extract/review) that you have already run
  through the gates, so an operator can switch in minutes. Canary's rules forbid
  silent automatic fallback, so this is an operator switch, not failover.
- **Price stability.**
  - Gemini Flash doubles on Jan 1.
  - DeepSeek has peak windows.
  - OpenRouter routes can change the upstream host. Pin the provider and keep
    `require_parameters`.
  - Recheck `litellm_pricing_overrides.yaml` against provider pages at each
    re-qualification.
- **Manuscript data handling.** Users upload unpublished novels. Before routing
  paid user traffic to OpenRouter-hosted open models, check each upstream host's
  retention, training and jurisdiction terms. Prefer first-party or zero-retention
  endpoints. This is a trust issue, not only a cost issue.
- **Lifecycle.** Pin snapshots, track retirement dates (Opus 5 is legacy), and
  re-qualify before migrating. Text models can change freely between runs; only
  Draw editions are immutable.
- **Refusals are a first-class quality metric** for a literature product. Show a
  refusal as a clear, recoverable state, and record it separately from quality.
- **Latency.** Adapt takes ~13 minutes wall time. Batch/Flex (half price) suits an
  optional "overnight" mode for Extract/Adapt/Plan, but not interactive
  corrections.

## Proposed next steps

1. Swap `claude-opus-5` for `claude-opus-5-5`: gateway, catalog and pricing
   override (forward-only).
2. Move reasoning effort from gateway routes to per-stage configuration, and
   record effort on usage events.
3. Restructure Adapt review/blueprint prompts so shared content comes first; add
   Anthropic cache breakpoints; measure cache-hit tokens.
4. Instrument Plan token totals on the next real run so its budget is measured,
   not modeled.
5. Build the Gate 0–2 harness over the fixtures. Run Visual review (Luna vs
   Gemini 3.8 Flash vs Sol) and Plan (Sol vs Luna) first, since those are the
   cheapest decisions with the biggest effect.
6. Add a stage spend ceiling (2× estimate) that pauses with a resumable state
   instead of draining the provider balance.

## Sources

- OpenAI: [GPT-6 Sol and Luna announcement](https://openai.com/index/introducing-gpt-6-sol-and-luna/), [pricing](https://developers.openai.com/api/docs/pricing); secondary spec/benchmark summary: [Kingy AI GPT-6](https://kingy.ai/blog/gpt-6-sol-luna-specs-benchmarks-pricing-comparison/), [VentureBeat](https://venturebeat.com/technology/openai-releases-gpt-6-sol-and-luna-models-slashing-api-costs-50-or-more)
- Anthropic: [models overview](https://platform.claude.com/docs/en/about-claude/models/overview); Opus 5.5 benchmarks: [Kingy AI Opus 5.5](https://kingy.ai/blog/claude-opus-5-5-specs-benchmarks-pricing-comparison/)
- Google: [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/latest-model), [price change summary](https://www.eesel.ai/blog/gemini-3-8-flash)
- Open models: [DeepSeek V4.1 Flash](https://venturebeat.com/technology/deepseek-v4-1-flash-debuts-with-0-003-1m-off-peak-cached-input-rate-and-benchmarks-eclipsing-gpt-5-6-sol-claude-opus-5), [MiMo V2.6](https://www.eesel.ai/blog/xiaomi-mimo-v2-6), [Kimi K3 / GLM pricing](https://www.morphllm.com/llm-api)
- Leaderboards: [Artificial Analysis](https://artificialanalysis.ai/leaderboards/models), [EQ-Bench Creative Writing v3](https://eqbench.com/creative_writing.html), [creative writing vs humans](https://www.digitalcitizen.life/creative-writing-benchmark-finds-frontier-ai-models-near-amateur-human-writers-but-behind-professionals/), [Fiction.LiveBench](https://fiction.live/stories/Fiction-liveBench-Feb-21-2025/oQdzQvKHw8JyXbN87)
- Long context: [Context rot guide](https://www.morphllm.com/context-rot), [long-context benchmark roundup](https://yage.ai/share/long-context-benchmark-en-20260315.html)
- Adaptation research: [R² novel-to-screenplay](https://arxiv.org/abs/2503.15655), [DSR decomposed screenwriting](https://arxiv.org/html/2510.23163v3), [MangaFlow](https://arxiv.org/abs/2605.28173)
- Structured output: [JSONSchemaBench](https://arxiv.org/pdf/2501.10868), [Structured Output Benchmark](https://arxiv.org/html/2604.25359v1)
- Judges: [bias mitigation evaluation](https://arxiv.org/pdf/2604.23178), [self/other label bias](https://arxiv.org/html/2608.18091)

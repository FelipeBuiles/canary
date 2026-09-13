# Model selection overhaul — September 11, 2026

Status: Historical constraint audit, followed by implemented simplification on September 11. Model placement remains an evaluation hypothesis, not measured creative quality. No paid generation was run.

Update: API and Codex can now mix freely within all listed jobs and auto-chains. The job-wide funding scope and linked-step warnings were removed. Only API portions are estimated/reserved/settled; Codex keeps diagnostic usage events without ledger entries. The original dev gate and fixed Draw edition profile remain. The constraint table and implementation sequence below record the pre-change findings; [current account model settings](../reference/account-model-settings.md) is authoritative.

## What is actually constrained

| Relationship | Current behavior | Hard provider limit? |
|---|---|---|
| Extract / Brief | Different models allowed; action admission requires the same funding source | No. Separate stage calls and reservations already exist |
| Adapt / Plan | Different models allowed, including different Codex reasoning models; action admission requires the same funding source | No. Separate artifacts and stage reservations already exist |
| Style / Cast text | One shared `prompt_model` selection | No. Configuration granularity |
| Style / Cast images | One shared `image_model` selection | No. Configuration granularity; preserve reference compatibility |
| Style text / images | A combined operation requires one funding source | Canary accounting constraint |
| Draw / OCR | Different image/text models; one funding source for combined page work | Canary accounting constraint |
| Visual review | Independent text/vision model and operation | Requires image input, not model equality |
| Existing Draw edition | One immutable generation profile | Intentional product/artifact contract; keep it |

`Config.effective_*_model()` returns each selected field independently. The old `require_same_text_target()` function in `codex_dev.py` has no callers. It is not an active limitation. `model_catalog.py` exposes the funding groups; `server/codex_admission.py` defines actual stage and action manifests. `classify_operations()` rejects mixed API/subscription operations, and `funding_scope()` / `assert_request_funding()` enforce admitted funding at execution. Different API providers all count as API funding, so Opus Adapt plus Luna Plan is already permitted.

`server/routers/pipeline.py::_run_stage_with_credits()` runs each chained stage through its own credited wrapper, after action-level admission. This makes Extract/Brief and Adapt/Plan the easiest funding pairs to separate. It does not make deleting `classify_operations()` safe: estimates, queued job funding, reservations, context propagation, cancellation, recovery and settlement all depend on its contract.

Stage artifacts are the handoff, not a shared provider conversation. Claude restrictions on moving internal thinking blocks between model versions therefore do not require Canary's adjacent stages to share a model.

## Where to spend

| Work | First trial | What must remain good |
|---|---|---|
| Extract | Luna against Terra baseline | Whole-book entity/state recall, late-book facts, exact visual anchors, source fidelity and valid artifacts |
| Brief | Luna; Terra for difficult editorial constraints | Faithful interpretation of requested changes and consistent adaptation scope |
| Style/Cast text | Luna | Anchor preservation and clear reference instructions; avoid unnecessary embellishment |
| Adapt | Compare Opus 5 with Terra; add Fable 5.1 and Astra as premium challengers | Narrative treatment, pacing, character voice, dialogue, exact lettering, page density and fidelity |
| Plan | Keep Terra initially; trial Luna on the same accepted Adapt artifact | Drawable action, explicit entity/state mapping, continuity, panel composition and lettering capacity |
| OCR | Trial Luna against existing successful checks | Missed lettering defects, accents/punctuation, small balloons and false redraw triggers |
| Visual review | Keep a capable vision baseline, then compare cheaper candidates | Identity/state drift and composition; do not infer visual correctness from OCR |
| Finish | No independent text model setting | Packaging and deterministic checks do not benefit from premium creative generation |

Adapt is the clearest creative investment: `book_adaptation.py` authors narrative treatment, blueprint, book adaptation and lettering under the same selected model. Plan's map/detail work is primarily spatial and structural. A future finer-grained selector could separate Adapt treatment/lettering from bounded repair work, but requires measuring actual calls and preserving the stage's artifact authority. Do not split these merely because they have different function names.

Start with **Luna Extract/Brief/Style text, Opus 5 Adapt, Terra Plan**, all API-funded, as an experimental profile. Keep the current defaults until the comparison passes. Use Astra/Fable where blind review demonstrates a benefit over Opus/Terra. Model expense and coding benchmarks do not establish better literary voice.

The newly added API choices are `gpt-6-astra`, `claude-fable-5-1`, and `claude-opus-5`. The account panel discovers them from the backend catalog. Gateway routes, provider registry, pricing aliases and request formatting are included. Configure `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` and restart the gateway/backend to load changes. Existing selections and Draw editions are not automatically changed.

Standard uncached input/output prices per million tokens are $10/$50 for [Astra](https://developers.openai.com/api/docs/models/gpt-6-astra), $10/$50 for [Fable 5.1](https://platform.claude.com/docs/en/models/fable-5-1/overview), and $5/$25 for [Opus 5](https://platform.claude.com/docs/en/models/opus-5/overview). Astra has long-input surcharges. Tokenization, caching, reasoning, failures and repairs affect actual task cost. Astra's route uses low reasoning effort; Claude routes use native adaptive thinking with provider-default effort. Comparisons must record this difference.

## Refusals and The Flowers

The reported Sol refusal is a useful regression case, not sufficient evidence to rank model families. The sample exists at `samples/theflowers.txt`, but the exact failed request/response and its model route were not recovered in this audit. Do not attribute it to a specific policy, copyright, story topic, or Codex-versus-API behavior without those records.

Fable 5.1 and Opus 5 explicitly have safety classifiers and may refuse benign work; higher price does not imply fewer refusals. Anthropic documents pre-output and mid-stream refusals and category-specific behavior in [Refusals and fallback](https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback). That is not a measured literary refusal ranking. Canary does not enable automatic model fallback in these routes.

Evaluate the exact manuscript extraction request with fixed prompts and models. Record provider, transport (Codex or API), model, effort, refusal fields, malformed output, schema failure, truncation, latency and total cost separately. A successful extraction must also preserve difficult subject matter accurately; omission is not success. User-directed model changes should be explicit and recorded, with no silent fallback or retry after ambiguous paid image submissions.

## Proposed implementation order

1. Keep today's independent model choices; expose the premium candidates (implemented here).
2. Decouple funding for Extract→Brief and Adapt→Plan by admitting, estimating and recovering each stage independently. A downstream credit failure must preserve the completed upstream artifact and provide a resumable state. Add mixed-funding cancellation/restart and settlement tests before removing the warning.
3. Split funding inside Style and Draw only after each sub-operation can reserve and settle API spend separately from subscription work. Preserve saved pixels if OCR cannot proceed. Never regenerate a paid image to recover an OCR/accounting failure.
4. Consider separate Style/Cast and Adapt subtask controls only after call-level cost and quality measurements justify the extra settings.
5. Compare fixed representative manuscripts and accepted artifacts blindly. Include The Flowers, long novels, dialogue-heavy scenes and multilingual lettering. Optimize cost per accepted page, including repair/redraw costs, rather than token prices alone.

## Verification scope

Account tests exercise independent premium/API choices, distinct Codex models in a linked pair and existing mixed-funding rejection. Client tests cover native Claude schema payloads and omission of unsupported sampling parameters. Pricing tests resolve all three premium models from the checked-in cache. The installed pinned gateway was also checked with in-memory HTTP responses, without provider requests. These checks establish wiring, not account access, live schema acceptance for every stage, quality or refusal rates.

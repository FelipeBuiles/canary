# Canary model selection and batch generation review

**Status: Proposed. Research checked September 9, 2026.** This is a recommendation,
not a model migration or a measured quality benchmark. No paid model calls were
made for this review. Checked-in configuration establishes the inventory below;
an individual deployment or project can override it.

## Decision

Keep **GPT-5.6 Terra for Adapt and Plan** as the preferred creative baseline from
the dev workflow. Trial **GPT Image 2.5 Sunburst and Flare through the public Image
API**, with a separate complete-page profile for each. Evaluate the lowest quality
setting that preserves the required lettering, anatomy, state, and visual style.
Do not select a winner from token price or provider marketing alone.

For cost reduction, pursue two independent paths:

1. **Vertex Flex for the existing Gemini image model:** a smaller integration
   than durable Batch, preserving the existing model while obtaining discounted
   processing. Check actual latency, availability, input size, and billing.
2. **OpenAI Batch for first-pass book Draw:** a good architectural fit once the
   selected GPT image variant passes the paired quality test. Keep interactive
   Style selection and individual revisions on standard processing initially.

Use cheap hosted models for bounded supporting text before replacing book-wide
creative work. The detailed text shortlist and its conditions are linked below.

## What is actually configured

| Work | Checked-in production gateway | Dev startup default |
|---|---|---|
| Extract and Brief | Gemini 3.8 Flash, every Extract preset | GPT-5.6 Terra |
| Adapt | Haiku 4.5 fast; Gemini 3.8 Flash balanced; Opus 4.7 quality | GPT-5.6 Terra |
| Plan | Gemini 3.5 Flash-Lite fast; Gemini 3.8 Flash balanced/quality | GPT-5.6 Terra |
| Supporting text: style suggestions/briefs, instructed asset rewrites | Gemini 3.5 Flash-Lite | GPT-5.6 Terra |
| Page OCR and optional visual review | Gemini 3.8 Flash through the same OCR alias | GPT-5.6 Terra |
| Generic image assets | Flash Lite Image fast; Gemini 3 Pro Image balanced; GPT Image 2 quality; explicit Reve/Seedream routes | Codex image tool, reasoning selector GPT-5.5 |
| Complete-page Draw | Fixed Gemini 3 Pro Image profile, 1696×2528, eight references maximum | Experimental Codex complete-page profile, five references maximum |
| Finish packaging/normalization | Deterministic work, with required checks and corrections as applicable | Same stage responsibilities |

Sources: [gateway configuration](../../litellm/config.yaml),
[runtime configuration](../../novel_to_comic/src/novel_to_comic/config.py),
[dev startup](../../scripts/dev.sh),
[complete-page adapter](../../novel_to_comic/src/novel_to_comic/page_drawing.py),
[visual review](../../novel_to_comic/src/novel_to_comic/page_visual_review.py).
See the [pipeline audit](model-pipeline-audit-2026-09-09.md) for call-site details.

The distinction matters: retaining the GPT results in production requires an
explicit production route. The committed production Adapt/Plan aliases currently
do not point to GPT. The dev image reasoning model does not identify the image
backend; the inspected tool fixes a `gpt-image-2` selector and does not expose a
Sunburst/Flare selector. Subscription-funded dev usage has unknown API-equivalent
USD cost. See [the dev capability report](../reference/codex-dev-capabilities.md).

Changing `image-quality` alone will not migrate Draw. Draw validates a separate,
edition-wide capability profile. A new image model needs its own adapter/profile,
reference and dimension checks, pricing, and provenance. Existing editions must
retain their producing model; use a new edition/project for the comparison.

## Image decision and economics

The exact new IDs are `gpt-image-2.5-sunburst` and `gpt-image-2.5-flare`, with
September 8 snapshots. Both accept text and images. Their standard rates per
million tokens are $5 text input, $8 image input, and $30 image output. Rates alone
do not establish cost per page: output token consumption depends on variant,
quality, and size. The GPT Image 2 calculator is not a 2.5 estimator.
[Sunburst model documentation](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst),
[Flare model documentation](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare).

The candidate set is Sunburst for fidelity, Flare for lower latency, the current
Gemini 3 Pro Image as control, and a lower-cost Gemini/Seedream challenger.
Qwen Image Edit and FLUX Klein deserve a separate open-weight trial, especially
for assets; their reference capacity and full-page lettering must be demonstrated.
The [image research](image-model-research-2026-09-09.md) gives exact routes, prices,
license distinctions, and feasibility constraints.

For measured GPT usage, use:

```text
standard image request USD =
  (5 × uncached text-input tokens + 1.25 × cached text-input tokens
   + 8 × uncached image-input tokens + 2 × cached image-input tokens
   + 30 × image-output tokens) / 1,000,000
```

Record actual cache and service-tier usage rather than assuming every repeated
reference is cached. Add OCR, visual review, failed metered attempts, and explicit
revisions. A Responses-based image workflow may also add orchestrator tokens;
direct Image API requests avoid that extra model layer.

### A concrete baseline, not a whole-book quote

Using Canary's **configured estimates**, 100 pages with four references each and
one OCR call per page cost:

| Scenario | Image component | OCR allowance | Total |
|---|---:|---:|---:|
| Current standard Gemini profile | $13.848 | $0.400 | $14.248 |
| Same image component at 50% discount | $6.924 | $0.400 | $7.324 |

Formula: `100 × (0.134 + 4 × 0.00112)` plus `100 × 0.004` OCR.
That is approximately **48.6% lower Draw-plus-OCR estimated cost**, not 50% off
the complete book. This illustration excludes image prompt/thinking charges not
represented by the fixed estimator, Style/Cast/cover generation, creative text,
visual review, redraws, and infrastructure. It is not measured provider billing.
The old panel-based [pricing proposal](pricing-and-margin.md) cannot supply a
current book-cost baseline.

Google currently publishes Gemini 3 Pro Image output at $0.134 standard and
$0.067 Batch/Flex for 1K/2K. Its cheaper image models require matching resolution
before comparison. [Google image pricing](https://ai.google.dev/gemini-api/docs/pricing).

Compare **total provider spend per accepted page**, including reference inputs
and every correction. A cheaper first image can become more expensive if it
requires more redraws. Keep lettering acceptance and human visual acceptance
separate; OCR cannot certify artwork quality.

## How batches would affect Canary

OpenAI explicitly supports both `/v1/images/generations` and `/v1/images/edits`
in Batch, with a 50% discount and a 24-hour processing window. Requests use unique
IDs; input files contain one model. JSON image edits can reference uploaded files
or image URLs, so approved references do not require multipart Batch uploads.
[Batch guide](https://developers.openai.com/api/docs/guides/batch),
[image edit API](https://developers.openai.com/api/reference/resources/images/methods/edit).

Canary's pages depend on approved style, character/location states, and canonical
Plan output. They do not form a previous-page image chain. After those inputs are
frozen, first-pass pages can be submitted independently. Batch changes Draw's
execution lifecycle, not Adapt's authority or the eight-stage order.

Recommended flow:

```text
approved references + canonical Plan
  → freeze and validate each page request
  → reserve and persist batch manifest
  → submit and persist provider job identity
  → await/reconcile provider job across restarts
  → import each result and settle its actual usage once
  → OCR saved pixels and retain check evidence
  → Draw review checkpoint
  → Finish preflight and export
```

Required engineering work:

1. **Durable external jobs.** Persist submission intent before network I/O, batch
   and file IDs, per-item correlation, frozen input hashes, result/error locations,
   and import/settlement acknowledgements. A timeout after submission is ambiguous;
   neither request hashes nor `custom_id` guarantee provider deduplication.
2. **Restart and deployment behavior.** Current in-process jobs become failed or
   recoverable on restart. External batches can keep running. Recovery must query
   and import existing jobs instead of resubmitting images; drain must distinguish
   local mutation from safely persisted external work.
3. **Billing lifetime.** Current owned holds renew from the running process. A
   day-long external job needs durable reservation ownership/reconciliation through
   downtime, partial results, expiry, and cancellation. Release only provably unused
   amounts; cancellation can leave completed, billable items.
4. **Per-page import.** Validate bytes, model, dimensions, request identity and
   reference provenance. Preserve output before settlement and OCR. Handle
   duplicate or out-of-order results idempotently. Never treat batch completion as
   proof that every page succeeded.
5. **Correction and mutation rules.** Prevent conflicting page revisions while
   submitted work is unresolved. Keep user-requested corrections interactive at
   first, on the same edition's image model. A later correction batch is a new
   explicitly authorized revision action.
6. **Status and UI.** Show queued externally, generating, importing, text checking,
   partially complete, and needs recovery. Refetch persisted status after reconnect;
   SSE is only a live update channel. Keep generated and checked page counts distinct.

Start with one project/edition per batch, chunked by payload size and provider
limits. Cross-customer packing saves no additional percentage and complicates
cancellation, billing ownership, and deletion. Keep OCR standard initially to avoid
another batch window after images finish. The Draw checkpoint and Finish gates
must remain in place.

### Flex as the earlier cost experiment

Vertex Flex supports the existing Gemini 3 Pro Image model on the global endpoint
and uses lower-priority synchronous processing. It is a smaller fit to Canary's
current request/response adapter than Batch. Google documents longer timeouts and
an inline payload limit; availability is not guaranteed.
[Vertex Flex documentation](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/flex-paygo),
[Vertex pricing](https://cloud.google.com/gemini-enterprise-agent-platform/generative-ai/pricing).

Implement explicit service-tier configuration and usage/pricing attribution,
check the whole request against payload limits, and align client, gateway and
provider timeouts. Never silently fall back to standard-priced requests after an
ambiguous Flex submission. Flex is a useful same-model cost control even if GPT
2.5 ultimately wins the quality comparison.

## Recommended text and vision set

The first target configuration should be deliberately small:

| Intent | Recommended baseline | First challenger | Promotion condition |
|---|---|---|---|
| Extract | Keep Gemini 3.8 Flash production control; retain Terra dev control | GPT-5.6 Luna, DeepSeek V4 Flash | Full-book entity/source recall and schema pass rate hold |
| Brief, style suggestions, cast rewrites | Trial GPT-5.6 Luna against existing Flash-Lite | GLM-5.3-Flash after capability confirmation | Exact anchors survive and instructions are followed |
| Adapt | GPT-5.6 Terra | DeepSeek V4 Pro / GLM-5.3; Sonnet 5 as commercial comparator | Blind preference and preservation checks match Terra at lower total cost |
| Plan | GPT-5.6 Terra | GPT-5.6 Luna, then DeepSeek V4 Flash | Exact lettering allocation, coverage, and state bindings hold |
| OCR | Retain Gemini 3.8 Flash until evaluated | Luna / Qwen3.8-27B / GLM-OCR | No increase in missed lettering defects or spurious corrections |
| Optional visual review | Retain current vision route initially | Qwen3.8-27B / GLM-4.6V | Human-labelled identity/state/composition detection holds |

Luna's standard short-context rate is **$0.20/$1.20 per million input/output
tokens**, versus Terra's **$2/$12**. That makes it a strong first experiment for
supporting work. The 90% token-rate reduction is relative to an API Terra call,
not a measured saving versus Codex subscription usage. Larger context has a
separate tariff. [OpenAI pricing](https://developers.openai.com/api/docs/pricing).

The open-weight shortlist is substantive, not an afterthought:

- **DeepSeek V4 Flash/Pro:** strongest first hosted text comparison; verify current
  peak/off-peak tariff, output budget and JSON handling. Do not confuse JSON mode
  with enforced JSON Schema, or ordinary text models with experimental vision.
- **Qwen3.8-27B:** a practical multimodal open-weight candidate. Distinguish its
  native context and hosted international rate from other Qwen API products.
- **GLM-5.3:** text quality challenger; **GLM-5.3-Flash** is especially inexpensive,
  but its full endpoint capability contract still needs confirmation.
- **GLM-OCR/4.6V:** focused vision alternatives. A document OCR model may read text
  cheaply but cannot replace reference-aware artwork review.

- **MiniMax M3:** another inexpensive multimodal, long-context hosted trial;
  confirm schema support before using it for canonical artifacts.
- **gpt-oss-120b on Groq:** a cheap schema-capable bounded-text control; its shorter
  context and lack of vision limit its role in whole-novel and page review work.

These choices, current prices, context limits, licenses where verified, and the
wider candidate scan are in the [text and vision research](text-model-research-2026-09-09.md),
with links to publisher and serving-provider sources. Open weights and cheap API
variants are not interchangeable concepts. Start hosted; self-hosting adds GPU
utilization, long-context memory and operational costs that cannot be inferred
from a model's license.

Do not automatically retain Opus 4.7 as the quality escalation after moving Adapt
to Terra. An escalation must solve a measured failure and carry an explicit cost
estimate; a higher-priced preset is not evidence of better adaptation.

## Trial plan and acceptance evidence

### 1. Establish comparable API controls

Capture exact producing model/endpoint and reasoning settings from a successful
dev run. Reuse its canonical inputs, prompts and schema normalization in a public
API Terra control; validate output under Canary's existing models. Matching names
across Codex and API do not guarantee identical execution or results.

Add synchronous GPT 2.5 capability profiles before attempting Batch. Include exact
model snapshot, quality, size, ordered authorities, edit-parent semantics, output
validation and actual token accounting. Test input limits without spending first.
Do not copy GPT Image 2's fixed output-token estimate into a 2.5 profile.

### 2. Compare image outputs in two passes

Use six representative pages for initial screening: dense dialogue; unusual
anatomy; multiple named characters; appearance-state change; location continuity;
and a less-graphic correction retaining identity. Compare Gemini control, Sunburst
medium/high, and Flare medium/high using equivalent fixed output dimensions and
the same canonical authorities. Use a new profile/edition per model-setting pair.

Then expand the best candidates to a held-out 12–20-page set, including repeated
generations and explicit corrections. Record exact lettering defects, human
visual acceptance, reference-limit failures, refusal rate, latency, usage, and
total correction spend. Treat a missing authority or incorrect model identity as
a contract failure, not a lower visual score. Test standard versus Batch/Flex on
the winning model separately so execution-tier savings do not get confused with
a model-quality change.

### 3. Evaluate text stages independently

Use complete short/medium/long works for extraction; a shortened excerpt does not
test late-book recall. Use the same accepted Story Bible/Brief for Adapt and the
same accepted adaptation for Plan. Test English, Spanish and French, punctuation,
source coverage, unusual anatomy, exact anchor preservation, and entity-scoped
state IDs. Keep deterministic checks authoritative and use blind human review for
narrative voice, pacing and visual readability. Record reasoning tokens and every
repair call in cost.

For OCR use human transcriptions of actual pages, including accents, tiny text,
intentional misspellings and irregular balloon order. Compare false acceptance
and false rejection of lettering, not only character error rate. Visual review
must separately inspect pages against approved references.

### 4. Promote in this order

1. Correct alias/pricing drift and establish usage-backed baseline costs.
2. Trial Luna for helper text and Vertex Flex for current image production.
3. Select a public API GPT 2.5 profile from paired quality and cost evidence.
4. Add optional durable Batch Draw with partial-result recovery and billing tests.
5. Promote open-weight winners by intent; preserve Terra creative output unless
   the held-out results justify replacing it.

The proposed implementation sequence preserves the original eight stages,
checkpoints, full-page lettering contract, and fixed model identity per edition.
It does not require a panel-generation redesign.

## Known gaps and required cleanup

- The configured **Reve direct API is retired** according to its official notice.
  Remove it from new production selection during implementation; do not retain its
  old price as an available alternative.
  [Reve retirement notice](https://help.reve.com/hc/en-us/articles/46837930295316-Reve-API).
- `extract-fast` resolves to Gemini 3.8 Flash in the gateway but to Gemini 3.5
  Flash-Lite in the [pricing aliases](../../novel_to_comic/src/novel_to_comic/litellm_pricing_overrides.yaml).
  Synchronize them and test alias/pricing consistency before reporting savings.
- Existing GPT image estimates are GPT Image 2-specific. New quality tiers and
  actual token usage need new metadata, not renamed aliases alone.
- OCR and visual review currently share a model selector. Trying different models
  for those jobs requires separate configuration while preserving cached-evidence
  identity and invalidation.
- Account model access, actual GPT 2.5 usage fields, request limits, discount
  attribution, and reference fidelity have not been tested by this research.
- The dev adapter cannot establish API dollar cost or select the exact 2.5 image
  variants. Use it for qualitative iteration within its documented limits.
- All per-book figures here are declared scenarios. A production budget requires
  measured text, image, OCR, correction, and failed-request usage from complete pages.

Supporting reports: [image providers and discounts](image-model-research-2026-09-09.md),
[text and vision providers](text-model-research-2026-09-09.md),
[repository and batching audit](model-pipeline-audit-2026-09-09.md).

# Image model and discounted execution research

Status: **Proposed**. Official sources checked 2026-09-09. No paid model evaluation or runtime change was performed. Prices are USD provider costs, not Canary credits. Recommendations are workload hypotheses until tested against full lettered pages.

## Recommendation

Evaluate **GPT Image 2.5 Sunburst** for finished pages and precise corrections; evaluate **Flare** alongside it for initial page generation. First test **Vertex Flex PayGo** on the existing Gemini image routes: it offers the same published 50% discount as Batch with substantially less orchestration work. Then build durable OpenAI Batch execution for approved, independent page jobs if overnight delivery is useful.

Do not choose a winner by list price alone. Measure cost per accepted page, including required references, rejected generations, lettering repairs, OCR, and human correction time. Keep the current model as a control, use the same frozen Adapt/Plan artifacts and authorities, and select a fixed profile for each new Draw edition.

## GPT Image 2.5: verified product and pricing

The exact public IDs are `gpt-image-2.5-sunburst` and `gpt-image-2.5-flare`, with `2026-09-08` snapshots. OpenAI describes Sunburst as its most capable image generation/editing model, emphasizing editing precision; Flare emphasizes speed for everyday generation. Both accept image inputs. [Sunburst model](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst), [Flare model](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare).

Both publish these standard rates per million tokens: text input **$5**, cached text **$1.25**, image input **$8**, cached image **$2**, image output **$30**. Equal token prices do not imply equal per-image cost. The model page warns against using the GPT Image 2 calculator to estimate 2.5 consumption. [OpenAI pricing](https://developers.openai.com/api/docs/pricing), [Sunburst model](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst).

The image guide supports explicit `low`, `medium`, `high`, `xhigh`, `max`, and `auto` quality. Custom dimensions require multiples of 16, aspect ratios between 1:3 and 3:1, at most 3840 pixels per edge, and 655,360–8,294,400 total pixels. Above 2560×1440 is experimental. Start with fixed portrait dimensions and compare medium/high/xhigh rather than `auto`. Responses image-tool calls also incur the mainline text model's usage; direct Images calls avoid that extra orchestrator. The guide explicitly acknowledges remaining text-placement, composition, and character-consistency limitations. [Image generation guide](https://developers.openai.com/api/docs/guides/image-generation).

The edit API documents JSON `images: [{file_id: ...}]` or `images: [{image_url: ...}]`, up to **16 input images**, a 32,000-character prompt maximum, and support for both 2.5 variants. URL references may be normal URLs or base64 data URLs. This is directly relevant to Cast/style/continuity authorities; reference-conditioned generation need not be routed through Responses. [Edit API reference](https://developers.openai.com/api/reference/resources/images/methods/edit).

Account access and the exact usage returned for Canary's prompts remain untested. Documentation has minor inconsistencies: the model page marks streaming unsupported while the guide gives streaming examples; the edit response description still says usage is for GPT Image 1 only while the guide tells 2.5 users to measure usage. Resolve these with a small API contract test before relying on them.

## OpenAI Batch feasibility

**Yes: both `/v1/images/generations` and `/v1/images/edits` are explicitly supported.** The Batch guide publishes a **50% discount**, a 24-hour completion window, separate rate limits, 50,000 requests/200 MB per input file, and one model per file. Results can arrive out of order and must be matched by `custom_id`. Expired jobs retain completed results and charge completed work. [Batch guide](https://developers.openai.com/api/docs/guides/batch).

Use uploaded reference file IDs to avoid duplicating large base64 authorities across every page request. For implementation, each line would carry one frozen page request, its explicit model snapshot, quality, size, prompt, and ordered reference IDs. This is a proposed integration shape, not a tested API submission:

```json
{"custom_id":"edition-page-revision-requesthash","method":"POST","url":"/v1/images/edits","body":{"model":"gpt-image-2.5-sunburst-2026-09-08","images":[{"file_id":"file-example"}],"prompt":"Frozen compiled page prompt","size":"1024x1536","quality":"high","n":1}}
```

Proposed pipeline requirements:

- Persist an immutable request manifest, provider batch ID, reference uploads, and per-item states before waiting. Recover after process restarts by reconciling provider status.
- Keep submit, poll, collect, artifact validation, OCR, and checkpoint approval distinct. Submission is not a completed Draw stage.
- Reject stale results when their edition/revision/input hash no longer matches. Never overwrite newer revisions.
- Do not resend ambiguous paid submissions automatically. Reconcile provider IDs before deciding an item is safe to submit again.
- Preserve stage ownership and `StageRuntime` lifecycle/accounting. Batch transport must not call later stages or auto-approve Draw.
- Batch only requests whose dependencies are already fixed. The current complete-page Draw does not imply a previous-page image chain. If a future workflow introduced a newly generated continuity reference, that dependent request would require a later wave; this is a generic dependency constraint, not a claim about today's page chain. Cast prerequisites and approval checkpoints cannot be compressed into one batch.
- Keep interactive corrections synchronous initially. A second batch for lettering repairs may add another overnight wait.

## Gemini: cheaper execution of the existing model

The current repository image catalog maps `image-fast` to Vertex `gemini-3.1-flash-lite-image`, `image-balanced` to Vertex `gemini-3-pro-image`, and `image-quality` to OpenAI GPT Image 2. Source: `novel_to_comic/src/novel_to_comic/image_models.py`.

Vertex's current official pricing page lists **Flex/Batch** rates at half the standard image rates: Pro Image **$120 → $60/M output tokens**, Flash Image **$60 → $30**, Flash-Lite Image **$30 → $15**. Pro uses 560 tokens/reference and 1120 output tokens for 1K/2K; Flash and Flash-Lite use 1120/reference. [Google Cloud pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing).

Vertex Flex officially supports all three image models, on the **global endpoint only**. Set `X-Vertex-AI-LLM-Request-Type: shared` and `X-Vertex-AI-LLM-Shared-Request-Type: flex` for Flex-only execution. Inline request payloads are limited to 20 MB; larger inputs require Cloud Storage references. Timeouts can reach 30 minutes and expected latency is longer than standard. [Flex PayGo](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/flex-paygo).

This is a real option for the current transport: `litellm_handlers/vertex_multimodal.py:267` creates `genai.Client` without HTTP options; `_vertex_location` defaults to global. Proposed work includes explicit execution-tier configuration, HTTP options, end-to-end timeout handling, tier-aware usage accounting, and no silent standard-price fallback. It should be much smaller than durable Batch orchestration, although payload sizes and deployment timeouts must be tested.

Vertex Batch also explicitly supports these models. Its documentation says most jobs finish within 24 hours **after execution starts, excluding queue time**; this is different from promising a 24-hour end-to-end experience. [Vertex batch inference](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/batch-prediction-gemini).

The separate **Gemini Developer API** also publishes Pro Image Flex/Batch, Flash Image Batch, and Flash-Lite Image Batch discounts. These corroborate economics but are not the transport Canary currently uses. Switching to that API would change authentication, file handling, quota, and billing integration. [Developer API pricing](https://ai.google.dev/gemini-api/docs/pricing).

## Illustrative 100-page economics

Assumptions: one successful image/page; 8 unchanged reference images/page; 2,000 prompt text tokens/page; no cache, retries, generated text/thinking, style/Cast generation, storage, or taxes. All Google requests use global pricing. Numbers are calculated from the official token rates above, not observed Canary bills.

| Model / output | Standard image calls, including references/prompt | Flex or Batch image calls | Plus synchronous OCR/review cost `V` |
|---|---:|---:|---|
| Gemini Pro Image, 1K/2K | $14.736 | $7.368 | $14.736 + V → $7.368 + V |
| Gemini Flash Image, 2K | $10.628 | $5.314 | $10.628 + V → $5.314 + V |
| Gemini Flash-Lite Image, 1K | $3.634 | $1.817 | $3.634 + V → $1.817 + V |

For example, if OCR/review costs $1 for the book (an illustrative assumption, not a quote), Pro's combined total is $15.736 → $8.368: **46.8% savings**, not 50%. Extra repairs reduce the discount's effect further.

For GPT Image 2.5, measure aggregate uncached text tokens `T`, image-input tokens `I`, and image-output tokens `O`. Standard image cost is `(5T + 8I + 30O)/1,000,000`; expected Batch image cost is half that under published Batch pricing. Add OCR/review and repairs separately. No credible fixed dollars-per-page estimate is available without those measured tokens. Cached input should be credited only when actually reported.

## Other image candidates, including open weights

### Already wired: Seedream and Reve

**Seedream 5.0 Lite** remains a useful inexpensive challenger: fal publishes **$0.035/image** for generation and editing, unchanged by supported resolution, with up to **10 references**. Its provider guide warns that excess references are silently reduced to the last ten, so Canary must keep rejecting overflow before submission. The provider's own guide also flags unreliable dense small text; that makes lettering-heavy pages an essential acceptance test. For 100 single successful outputs, the published image charge is **$3.50**, before OCR, repairs, and other stages. [fal Seedream Lite guide](https://fal.ai/learn/tools/how-to-use-seedream-5-lite).

**Seedream 5.0 Pro editing** also supports **10 references**. fal labels current pricing **tentative**: output area ≤1536×1536 costs **$0.0675 + $0.0045 per additional input image**; above that and through 2048×2048 costs **$0.135 + $0.0045 per additional input image**. The first input is free. With eight references this is **$0.099/image** at the smaller tier or **$0.1665/image** at the larger tier: **$9.90 or $16.65 per 100**, before OCR/repairs. This removes much of Lite's cost advantage. Keep it as a quality challenger, not an automatic cheaper replacement. Provider queueing and multiple outputs are not evidence of a 50% Batch discount. [fal Seedream Pro endpoint](https://fal.ai/models/bytedance/seedream/v5/pro/edit).

**Reve's direct API should be retired from new production selection pending any explicit vendor restoration.** Its current official support article says the API sunset on **August 14** and is no longer available, with unused-credit refunds before **August 31, 2026**. This is later evidence than the July 14, 2026 Reve 2.1 launch blog. Do not use older per-image prices as current quotes or interpret the still-wired `reve/create` alias as availability evidence. No live endpoint was tested and no configuration was changed. Third-party hosted Reve models would require a separate availability and contract evaluation. [Reve API retirement notice](https://help.reve.com/hc/en-us/articles/46837930295316-Reve-API), [earlier API launch](https://blog.reve.com/posts/the-reve-api/).

### Additional candidates

| Candidate | Verified economics/capability | Recommendation for Canary |
|---|---|---|
| FLUX.2 Pro | From $0.03 first output MP, $0.015/additional MP, $0.015/reference MP; API supports 8 references | Useful multi-reference comparison; reference charges can erase headline savings |
| FLUX.2 Flex | Current pricing page lists $0.05/MP for inputs/output; typography emphasis | Test lettering-rich pages; the older docs still quote $0.06, so prefer current pricing and verify billing |
| FLUX.2 Klein 4B | From $0.014; Apache 2.0 weights; ~13GB VRAM; 4 references | Economical experiments or simple pages, but 4-reference cap often disqualifies full Cast/style/location authority sets |
| FLUX.2 Klein 9B | From $0.015; ~24GB VRAM; default weights license is noncommercial; 4 references | Hosted evaluation is easy; commercial self-hosting needs appropriate rights |
| Qwen Image Edit 2511 | Apache 2.0; publisher emphasizes reduced drift and multi-person consistency; multiple image inputs | Serious open-weight candidate for identity/editing evaluation; hosted/GPU cost must be measured |

Sources: [BFL current pricing](https://bfl.ai/pricing?category=flux.2), [FLUX.2 overview and limits](https://docs.bfl.ai/flux_2/flux2_overview), [Qwen publisher model card](https://huggingface.co/Qwen/Qwen-Image-Edit-2511).

A reference-cost example: a 2MP Pro output plus eight reference images, **each billed as 1MP**, costs $0.03 + $0.015 + 8×$0.015 = **$0.165** under BFL's rounding rules, before retries. BFL's documented “batch” multiplies price by image count; it is not a documented 50% asynchronous discount. [BFL current pricing](https://bfl.ai/pricing?category=flux.2), [BFL pricing overview](https://docs.bfl.ai/quick_start/pricing).

Never remove authorities to fit a cheaper model. Open weights remove model-access fees, not GPU, operations, or QA cost. None of these publisher claims establishes equal performance on Canary's complete lettered comic pages.

## Evaluation sequence

1. Freeze 12–20 representative accepted page requests: dense lettering, crowd scenes, recurring characters, unusual states, props, location continuity, and less-graphic corrections.
2. Compare the production complete-page Gemini 3 Pro Image baseline with Sunburst and Flare at fixed sizes and quality levels. Include GPT Image 2 as an additional control for assets/editions that actually used that profile. Use real API billing/usage, not Codex subscription consumption, for production economics.
3. Run the same Gemini control through standard and Flex; measure accepted-page rate, wall time, timeout behavior, payload limits, and actual charges.
4. Evaluate FLUX.2 Pro/Flex and Qwen Edit only on requests whose required authorities fit; record reference-limit failures as capability failures rather than dropping inputs.
5. Choose on exact lettering checks plus visual review of composition and continuity. OCR success alone cannot establish visual quality.
6. Implement Batch only after proving image model quality and establishing that enough pages can execute in independent waves to justify the operational complexity.

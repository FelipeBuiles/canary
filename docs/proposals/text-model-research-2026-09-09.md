# Text and vision model research — 2026-09-09

Status: research proposal; no runtime or routing changes. Prices are USD per million tokens, uncached standard inference unless noted. Researched against provider documentation; no paid evaluations were run. These recommendations are hypotheses for Canary, not claims that general benchmarks establish comic quality.

## Recommendation

Keep **GPT-5.6 Terra for Adapt and Plan**, matching the default development adapter. Trial **GPT-5.6 Luna** for bounded brief/style/cast text work and extraction, **DeepSeek V4 Flash** as the leading inexpensive open-weight text challenger, and **Qwen3.8-27B** as the leading open-weight multimodal challenger. Keep the existing OCR model until a lettering-specific evaluation demonstrates that an alternative misses no more defects. GLM-5.3 and GLM-5.3-Flash deserve trials, with the latter's capability details still needing confirmation.

The strongest savings opportunity in text is moving suitable helper calls off Terra, not replacing the user's successful adaptation/planning work immediately. An expensive image redraw can erase savings from many text calls. Price decisions should minimize cost per accepted page.

## What the checkout actually selects

[`scripts/dev.sh`](../../scripts/dev.sh) sets every default Codex text alias to `gpt-5.6-terra`, including extraction, adaptation, planning, prompts and OCR. The original-process route map can override these defaults, so a particular historical run's usage record remains authoritative. [`codex_dev.py`](../../novel_to_comic/src/novel_to_comic/codex_dev.py) treats subscription funding separately from API funding; subscription runs are not evidence of zero API cost.

[`litellm/config.yaml`](../../litellm/config.yaml) instead routes balanced extraction/adaptation/planning/OCR to Gemini 3.8 Flash. Prompt aliases use Gemini 3.5 Flash-Lite; fast Adapt uses Claude Haiku 4.5; quality Adapt uses Claude Opus 4.7. Therefore, preserving the development result in production means explicitly configuring Terra through the API, not leaving the balanced gateway untouched. There is no universal hardcoded GPT text default inside the adapter itself.

## Price and capability shortlist

| Model / provider | Input / output | Context and modality | Canary decision |
|---|---:|---|---|
| GPT-5.6 Terra / OpenAI | $2 / $12 | 1.05M; image input; structured outputs | Preserve Adapt and Plan baseline |
| GPT-5.6 Luna / OpenAI | $0.20 / $1.20 | 1.05M; image input; structured outputs | First low-friction helper challenger |
| GPT-5.6 Sol / OpenAI | $4 / $20 | 1.05M; image input; structured outputs | Only if Terra fails a specific quality requirement |
| Gemini 3.8 Flash / Google | $0.75 / $3.75 introductory | 1M; 64K output | Existing production comparator |
| DeepSeek V4 Flash / DeepSeek | $0.22 / $0.66 off-peak; $0.44 / $1.32 peak | 1M; 384K max output; JSON output | Leading cheap open-weight text challenger |
| DeepSeek V4 Pro / DeepSeek | $0.66 / $1.98 off-peak; $1.32 / $3.96 peak | Same advertised limits | Quality challenger after Flash |
| GLM-5.3 / Z.ai | $1.40 / $4.40 | 1M; 128K output; text only | Open-model quality challenger |
| GLM-5.3-Flash / Z.ai | $0.15 / $0.50 | Pricing verified; detailed model page unavailable | Promising, confirm capabilities before evaluation |
| Qwen3.8-27B / Alibaba international | $0.50 / $3 | Open weights; multimodal; native 262K, extendable to 1M | Open-weight extraction and vision trial |
| Qwen3.8-2.4T-A95B / Alibaba international | $2 / $6 | Open weights; text; hosted input tier to 1M | Lower priority: large model, modest input savings |
| Qwen3.8-Flash / Alibaba global | $0.113 / $0.382 | Hosted API variant; input tier to 1M | Cheap hosted challenger; do not assume identical to open Flash-Next weights |
| GLM-4.6V / Z.ai | $0.30 / $0.90 | Vision | OCR / visual-review challenger |
| GLM-OCR / Z.ai | $0.03 / $0.03 | Specialized OCR | Transcription experiment; cannot replace visual review |

OpenAI prices and short/long-context schedules: [official pricing](https://developers.openai.com/api/docs/pricing). Terra/Sol specifications: [model comparison](https://developers.openai.com/api/docs/models/compare). Luna supports disabling reasoning, and prompts exceeding 272K input tokens cost 2× input and 1.5× output for the whole request: [Luna model](https://developers.openai.com/api/docs/models/gpt-5.6-luna). Batch/Flex token prices are half standard; that is useful for offline evaluations but introduces asynchronous delivery.

Google's introductory Flash price expires December 31, 2026; January 1 rates become $1.50 / $7.50. This matters for durable budgets. Canary currently uses Vertex, so validate the precise account/region SKU before adopting Developer API rates as billing truth. [Google model announcement](https://ai.google.dev/gemini-api/docs/latest-model), [pricing](https://ai.google.dev/gemini-api/docs/pricing).

DeepSeek now uses peak/off-peak pricing. Peak is 01:00–04:00 and 06:00–10:00 UTC Monday–Friday; all other hours are off-peak. Old indexed pages still show obsolete $0.14 / $0.28 Flash pricing. The current canonical page was available in search extraction but direct retrieval timed out; confirm rates in the account before spending. JSON output does not establish strict schema enforcement. Its experimental `deepseek-v4-flash-vision-exp` is separately listed; do not treat normal V4 Flash as vision. [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/). Released Flash weights are MIT licensed; hosted revisions can differ from the original release. [Official model card](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash).

Z.ai's current pricing lists GLM-5.3, 5.3-Flash and the vision/OCR rates above. [Pricing](https://docs.z.ai/guides/overview/pricing). GLM-5.3 always reasons and accepts `low`, `high`, `max`; a disable-thinking parameter is unsuitable. [GLM-5.3 documentation](https://docs.z.ai/guides/llm/glm-5.3). GLM-5.2 remains $1.40 / $4.40 and supports text/JSON at 1M context, but 5.3 is the current comparison target. [GLM-5.2](https://docs.z.ai/guides/llm/glm-5.2). GLM-OCR targets document parsing; stylized comic lettering must be tested separately. [GLM-OCR](https://docs.z.ai/guides/vlm/glm-ocr).

Alibaba prices depend on region, deployment scope, input tier and exact model ID. The table deliberately distinguishes international open-weight hosting from global Flash API pricing. Batch and cache discounts cannot be combined where batch is supported. [Alibaba pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing). Qwen3.8-27B supports images/video and optional thinking. Its 1M self-hosted context requires scaling beyond native 262K, with possible short-context degradation. [Official 27B model card](https://huggingface.co/Qwen/Qwen3.8-27B). Qwen3.8-Max adds features such as vision beyond the open 2.4T release; do not assume API and weight capabilities match. [Official 2.4T model card](https://huggingface.co/Qwen/Qwen3.8-2.4T-A95B).

## Other candidates reviewed

Claude Haiku 4.5 is $1 / $5 with 200K context; the existing Opus 4.7 is $5 / $25 with 1M context. Current Sonnet 5 lists $2 / $10 and 1M context, making it a possible creative-writing comparator to Terra, but a small output-price advantage alone does not justify replacing results the user likes. Opus 4.7 is now a legacy model; retaining it as a default quality tier needs evidence. [Anthropic model comparison](https://platform.claude.com/docs/ja/models/opus-4-7/overview).

Kimi K3 advertises 1M context, always-on reasoning and JSON Schema output. The fetched pricing page omitted its dynamic price table, so no verified price is supplied here. K2.6 remains a multimodal alternative. Include Kimi only once the exact hosted rate and response contract are captured; do not recycle K2.5 prices for K3. [Kimi pricing index](https://platform.kimi.ai/docs/pricing/chat), [K3 capabilities](https://platform.kimi.ai/docs/pricing/chat-k3).

Self-hosting open weights is not automatically cheaper. Measure GPU memory, long-context KV cache, utilization, throughput, retries and operations against hosted marginal prices. Begin with hosted evaluations; a 27B model is a more realistic local experiment than a multi-trillion-parameter flagship. No self-hosted cost claim is made without hardware and traffic measurements.

## Evaluation and stage placement

1. **Extract:** compare Terra, existing Gemini, Luna, DeepSeek Flash and Qwen27B on complete short/medium/long novels. Score entity and appearance-state recall, chapter coverage, source support, exact anchors, missing late-book facts, output truncation and schema validity. Whole-book context claims alone do not prove extraction recall.
2. **Brief/style/cast text:** evaluate Luna first, then GLM-5.3-Flash and Qwen Flash if endpoint contracts check out. Score adherence to requested changes, preservation of established anchors and absence of invented entities. Keep deterministic prompt assembly deterministic.
3. **Adapt:** Terra stays. A blind challenger trial can use DeepSeek Pro, GLM-5.3 and Sonnet 5. Judge pacing, fidelity, dialogue voice, exact lettering and page density and lettering budgets in English/Spanish/French. Coding benchmarks are weak evidence for this task.
4. **Plan:** Terra stays initially; trial Luna before changing provider. Score semantic layout, drawable actions, visible-entity-to-state mapping, continuity, coverage and text capacity. Evaluate identical accepted Adapt artifacts to isolate planning quality.
5. **OCR:** compare existing Gemini/Terra against Luna, Qwen27B and GLM-OCR/4.6V using hand-transcribed real pages, including punctuation, accents, tiny text, overlapping balloons and intentional misspellings. Measure character error rate and, more importantly, missed lettering defects and false redraw triggers. OCR receives rendered pixels; avoid showing it expected text in ways that encourage copying rather than reading.
6. **Visual review:** compare page plus approved references using actual visual models. Score identity drift, costumes/state, missing entities, panel composition and continuity separately from lettering. OCR success cannot verify these concerns.

Use a fixed representative fixture set, log exact endpoint/model/reasoning parameters, and include failed calls plus reasoning tokens in costs. Compare paired outputs blindly with a human judging creative quality. Promote only on no material quality regression and a meaningful reduction in total accepted-page cost. Keep a final held-out fixture set to avoid overfitting prompts.

For illustration, a 100K-input/10K-output text call costs $0.32 on Terra, $0.032 on Luna, $0.1125 on promotional Gemini Flash, $0.0286 on off-peak DeepSeek Flash, and $0.0184 on GLM-5.3-Flash at their listed token rates. These are arithmetic scenarios, not measured Canary calls; tokenization and reasoning change actual usage. A small increase in redraw probability can overwhelm such per-call savings.

## Additional open-weight candidates and integration cautions

**gpt-oss-120b on Groq** is a useful bounded-text control: $0.15 input / $0.60 output, text only, 131,072 context and 65,536 maximum output, with JSON Schema mode. Its shorter context makes it unsuitable as a universal whole-novel replacement. It can compete for brief/style rewrites, but cannot do OCR or visual review. [Groq's exact hosted model specification](https://console.groq.com/docs/model/openai/gpt-oss-120b).

**MiniMax-M3** merits the same early hosted trial as DeepSeek Flash and Qwen27B: current direct standard API rates are $0.30 / $1.20 for inputs through 512K and $0.60 / $2.40 above 512K; priority is 1.5×. M2.7 remains $0.30 / $1.20, but using old M2.7-only summaries misses M3. [Current MiniMax pricing](https://platform.minimax.io/docs/guides/pricing-paygo). M3 has released multimodal weights with 1M context and enabled/adaptive/disabled thinking modes under the MiniMax community license. Endpoint-specific strict schema support and output limits should be checked before promotion. [Official weights](https://huggingface.co/MiniMaxAI/MiniMax-M3).

**Kimi K2.6** documents images up to a recommended 4096×2160 and video up to 2048×1080. Test resizing explicitly with Canary's portrait pages rather than assuming all page pixels reach the model unchanged. [K2.6 guide](https://platform.kimi.ai/docs/guide/kimi-k2-6-quickstart).

For every challenger, first run a small transport/schema probe before quality evaluation: nested Pydantic schema acceptance, enums, required fields, unsupported JSON Schema keywords, empty/refusal responses, reasoning-token accounting, image dimensions/reference counts, output-length limits and gateway parameter handling. “OpenAI compatible” or “JSON output” alone is insufficient proof of strict schema equivalence. Keep the same artifact validation after provider output. Existing automatic escalation paths and funding constraints also need review before mixing providers.

The gateway sends **all extraction presets**, including fast, to Gemini 3.8 Flash. Price estimates must follow the actual alias-to-provider mapping rather than infer cheaper extraction from the word `fast`; audit configured local price entries as part of any eventual change.

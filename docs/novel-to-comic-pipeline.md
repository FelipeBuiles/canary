# Novel-to-Comic/Animation Pipeline: Research Report & Architecture Plan

**Version 2.0 — April 2026**

## Executive Summary

Converting a full-length novel into a comic book (and eventually animation) using AI is now technically feasible as of April 2026 — though character consistency across 100+ panels remains the hardest unsolved problem. The recommended architecture is a **decomposed 7-stage pipeline**: global novel extraction → RAG index construction → scene-to-screenplay → panel breakdown → image prompt generation → image/video rendering → assembly. A 300-page novel can be converted to a 600-panel graphic novel for approximately **$25–35 at standard quality** or **$2–5 at budget quality**, with image generation — not LLM processing — as the dominant cost.

The most critical design decisions are:

1. **FLUX.2 multi-reference** (via API) for zero-training character consistency, or **SDXL + character LoRA + ControlNet** (via ComfyUI) for maximum quality at near-zero marginal cost
2. **Hybrid long-context + RAG** for book content: one full-novel pass to build a Story Bible, then per-panel RAG retrieval
3. **Decomposed LLM pipeline**: separate agents for extraction, screenplay writing, panel breakdown, and prompt generation — never end-to-end
4. **Text composited in post-processing**, never generated inside images

### What Changed Since V1 (March → April 2026)

| Area | Update |
|---|---|
| **Sora 2** | OpenAI announced full shutdown on March 24, 2026. App closes April 26; API closes September 24. Removed as a recommendation. |
| **FLUX.2 [klein]** | New family released Jan 15, 2026. Sub-second inference on consumer GPUs. 4B model is Apache 2.0 (commercial OK). Replaces FLUX.1 Schnell for prototyping. |
| **Hailuo v2.3** | Updated model line from MiniMax; Pro tier now at native 1080p. Pricing confirmed at $0.27–$0.48/video depending on tier. |
| **Commercial platforms** | LlamaGen.AI, Dashtoon, and Jenova have matured into full pipeline platforms with built-in character consistency. Worth evaluating before building from scratch. |
| **FLUX.2 [dev] VRAM** | Clarified: 32B params, requires ~64–90 GB VRAM. FP8 quantized versions now run on RTX 4090 via NVIDIA partnership. |
| **GPT Image 1.5** | Renamed from earlier references. OpenAI pricing confirmed. |

---

## 1. Image Generation: Tools, APIs, and Costs

### Hosted API Landscape

The image generation market in 2026 is dominated by FLUX (Black Forest Labs), with strong competition from OpenAI and Google.

| Provider | Best Model | Price/Image (1MP) | API | ControlNet | Multi-Reference | Comic Rating |
|---|---|---|---|---|---|---|
| Black Forest Labs | FLUX.2 [pro] | $0.030 | Yes | Yes (community) | Yes (8–10 refs) | Best |
| OpenAI | GPT Image 1.5 | $0.009–$0.250 | Yes | No | No | Moderate |
| Google | Gemini image models | Vertex AI pricing | Yes | No | Yes | Moderate |
| Stability AI | Stable Image Ultra | $0.009–$0.080 | Yes | Yes | No | Good |
| Ideogram | v3.0 | $0.025–$0.090 | Yes | No | No | Good (text) |
| Midjourney | v7/v8 | ~$0.033 (sub) | No official API | No | Via --cref | Good (no API) |

[BFL pricing](https://docs.bfl.ml/quick_start/pricing), [OpenAI pricing](https://platform.openai.com/docs/pricing/), [Google Vertex AI pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing), [Stability AI pricing](https://platform.stability.ai/pricing)

**FLUX.2 [pro] is the top recommendation** for a comic pipeline because it supports up to 8–10 reference images per API call — enabling character and style consistency without any model training ([Together AI blog](https://www.together.ai/blog/flux-2-multi-reference-image-generation-now-available-on-together-ai)). Feed 4–8 anchor images (face closeups, body poses, style samples) and the model locks onto those references. FLUX.2 uses a positive-only architecture — no negative prompts are supported.

Midjourney remains the highest artistic quality generator but lacks an official API, making it unsuitable for automated pipelines ([myarchitectai.com](https://www.myarchitectai.com/blog/midjourney-apis)). Ideogram 3.0 excels specifically at rendering legible text within images (~94% accuracy vs. ~78% for DALL-E 3), making it useful for text-heavy panels if speech bubbles are needed inside images ([AI Tools DevPro](https://aitoolsdevpro.com/ai-tools/ideogram-guide/)).

### Open-Source Models

| Model | VRAM | ControlNet | IP-Adapter | License | Comic Rating |
|---|---|---|---|---|---|
| SDXL 1.0 | 8 GB | Full suite | Full suite | Commercial OK | Best ecosystem |
| Illustrious XL | 8–12 GB | Full | Full | Commercial | Best for illustration |
| FLUX.2 [klein] 4B | ~8–13 GB | Emerging | Multi-ref native | Apache 2.0 | Good, fast prototyping |
| FLUX.2 [klein] 9B | ~20 GB | Emerging | Multi-ref native | Non-commercial | Better quality |
| FLUX.1 [dev] | 16–24 GB | XLabs/InstantX | Shakker Labs | Non-commercial | Good quality |
| FLUX.2 [dev] | 64–90 GB (FP8: ~24 GB) | Early stage | Emerging | Non-commercial | Best quality (impractical raw) |
| SD 3.5 Large | 12–24 GB | Official (limited) | Limited | <$1M revenue | Growing |

[AI Photo Labs comparison](https://aiphotolabs.com/compare/flux-vs-stable-diffusion-35-complete-2025-performance-comparison/), [HuggingFace Forums](https://discuss.huggingface.co/t/best-approach-in-2026-to-reproduce-a-specific-cartoon-style/173784)

**SDXL remains the strongest choice for self-hosted comic pipelines** due to its mature ControlNet + IP-Adapter ecosystem and 50,000+ community fine-tunes on Civitai. Illustrious XL and Pony Diffusion V6 XL are SDXL fine-tunes optimized for illustration and anime styles respectively ([AI Photo Generator](https://www.aiphotogenerator.net/blog/2026/02/best-stable-diffusion-models-2026)).

**NEW: FLUX.2 [klein] 4B** (released January 2026) is a strong new option for local prototyping. At 4B parameters with Apache 2.0 licensing, it runs on consumer GPUs (RTX 3090/4070) with sub-second inference. It supports text-to-image, single-reference editing, and multi-reference editing in a unified architecture. Its distilled variant generates images in 4 steps. LoRA training ecosystem and comic-specific fine-tunes are already appearing on Civitai.

### Serverless API Providers

Running open-source models without managing GPUs:

| Model | Fal.ai | Replicate | Together AI | BFL Direct |
|---|---|---|---|---|
| FLUX.2 [pro] (1MP) | $0.045–0.050 | ~$0.055 | $0.030 | $0.030 |
| FLUX.2 [klein] 4B | $0.009/MP | — | — | $0.014/MP (distilled) |
| FLUX.1 [dev] | $0.020–0.025 | $0.025 | $0.015–0.025 | — |
| SDXL | $0.003 | $0.005 | $0.0019 | — |

[Fal.ai pricing](https://fal.ai/pricing), [Replicate pricing](https://replicate.com/pricing), [Together AI pricing](https://www.together.ai/pricing)

**Together AI** offers the best value for FLUX.2 Pro at $0.030/image, matching BFL's direct pricing while providing an OpenAI-compatible SDK. For ultra-budget prototyping, SDXL via Together AI costs $0.0019/image. FLUX.2 [klein] via Fal.ai offers an excellent middle ground at $0.009/MP for rapid iteration.

### Cost Estimates: 150 Panels (Comic Chapter)

| Tier | Approach | Cost |
|---|---|---|
| Draft/prototype | FLUX.2 [klein] 4B via Fal.ai | <$2 |
| Mid-quality | FLUX.2 Dev via Fal.ai | ~$5–8 |
| Production | FLUX.2 Pro via Together AI/BFL | ~$5–10 |
| Premium | FLUX.2 Max or GPT Image 1.5 High | ~$12–40 |
| Self-hosted SDXL | After setup, marginal cost | ~$0 |

Self-hosting only breaks even at ~5,000+ images/month. For a pipeline generating 150–600 panels per project, serverless APIs are clearly more economical.

---

## 2. Character & Environment Consistency

This is universally identified as **the #1 unsolved problem** in AI comic generation. Every source — from academic papers to Reddit practitioners to commercial products — names character drift across panels as the dominant challenge ([Neolemon guide](https://www.neolemon.com/blog/ultimate-guide-to-creating-consistent-characters/)).

### Technique Comparison

| Technique | Consistency | Setup Effort | Per-Panel Cost | Multi-Character | Best For |
|---|---|---|---|---|---|
| LoRA training (20–50 images) | 80–90% | High (hours) | ~$0 self-hosted | Yes (multiple LoRAs) | Main characters, long-form |
| FLUX.2 multi-reference (8–10 refs) | 85–90% | Low (no training) | $0.03/panel | Yes (anchor packs) | API-driven pipelines |
| FLUX Kontext iterative editing | ~90–95% | Medium | $0.04/edit | Limited (1–2 chars) | Short series |
| IP-Adapter FaceID Plus v2 | 70–85% | Low | ~$0 self-hosted | Limited | Face consistency |
| StoryDiffusion (Consistent Self-Attention) | 75–85% | Low (training-free) | ~$0 self-hosted | Single character | Same-batch generation |
| Prompt-only (character anchors) | 60–75% | Minimal | $0 | Yes | Quick experiments |

### Recommended Approach: Layered Consistency Stack

The state-of-the-art for production comic work layers multiple techniques:

**For API-based pipelines (recommended starting point):**
1. Generate high-quality character reference sheets (front/3/4/side/back) using a strong model
2. Use FLUX.2 [pro] multi-reference with 4–8 anchor images per character per panel call
3. Apply the "Character Anchor" pattern — a fixed ~60-word physical description appended verbatim to every image prompt ([OpenAI prompting guide](https://developers.openai.com/cookbook/examples/multimodal/image-gen-1.5-prompting_guide/))
4. For dialogue panels requiring lip-sync later, use Flux Kontext editing from the anchor image

**For self-hosted pipelines (maximum quality):**
1. Train a Style LoRA on ~30–50 art style reference images
2. Train a Character LoRA per main character (10–20 curated images each, ~20–45 min on RTX 4090)
3. Use IP-Adapter FaceID Plus v2 (weight 0.7–0.9) for per-panel face conditioning
4. Use ControlNet OpenPose for body pose and proportions
5. ADetailer for face correction in post-processing
6. Never regenerate from scratch — always edit from the original character anchor image

**For environments:** Generate location "plates" (background images) once per location and composite characters onto them. For maximum quality, use rough 3D renders (Blender) as ControlNet depth/normal inputs for consistent spatial layout.

**For multi-character scenes (hardest sub-problem):**
- FLUX.2 multi-reference with separate anchor packs per character (4 images of character A, 4 of character B)
- Or: SDXL with dual character LoRAs + Regional Prompter (spatial masks assign different LoRAs to different canvas regions)
- Fallback: generate characters separately, composite via inpainting

### Emerging Tools (2025–2026)

Several recent breakthroughs are specifically addressing sequential art consistency:

| Tool/Paper | Innovation | Status |
|---|---|---|
| StoryDiffusion ([NeurIPS 2024](https://arxiv.org/html/2405.01434v1)) | Training-free Consistent Self-Attention across batch | 6,400 GitHub stars, production-ready |
| DreamingComics ([arXiv Dec 2025](https://arxiv.org/html/2512.01686v1)) | LLM layout + video DiT backbone, best on ViStoryBench | Research, code available |
| DiffSensei ([CVPR 2025](https://github.com/jianzongwu/DiffSensei)) | MLLM-as-identity-adapter for manga, MangaZero dataset | Released checkpoints, manga-only |
| CharaConsist ([ICCV 2025](https://murray-wang.github.io/CharaConsist/)) | First DiT-native (FLUX) consistency method | Research |
| PuLID/InfiniteYou/InstantID | FLUX-based face consistency without training | Community adoption growing |
| FLUX Kontext | Edit-based panel production at 90–95% fidelity | Production-ready via BFL API |
| StoryBlender ([arXiv March 2026](https://arxiv.org/html/2604.03315v1)) | Multi-subject story generation with blending | Recent research |

### Commercial Platforms (Evaluate Before Building)

Before building a full custom pipeline, these platforms are worth evaluating:

| Platform | Strength | Consistency Approach | Limitation |
|---|---|---|---|
| LlamaGen.AI | KDP-ready print output, full pipeline | Proprietary LoRA + reference sheet system | Less customizable |
| Dashtoon | Webtoon creation + monetization | Character library / trained models | Platform lock-in, vertical format focus |
| Jenova | 6 style templates, 200+ page consistency | Reference sheet architecture + plot memory | Newer, less battle-tested |

These platforms have matured significantly in early 2026 and may solve your use case without custom engineering. However, they offer limited control over the LLM pipeline (novel extraction, screenplay adaptation) which is where a custom pipeline adds the most value.

### Honest Assessment

With the best available techniques, **~85–92% consistency is achievable** across a skilled workflow. "Solved" claims from commercial products are marketing overstatement for complex sequential art with multiple characters. Comics beyond ~16 pages begin to exhibit drift even with best methods. Human review remains essential at scene/chapter boundaries.

---

## 3. LLM Storyboarding & Book Content Structuring

### The Decomposed Pipeline

Research from [EMNLP 2025](https://arxiv.org/html/2510.23163v3) demonstrated that decomposed pipelines dramatically outperform end-to-end generation — a two-stage approach achieved a **75% win rate** against frontier models in blind evaluations by professional screenwriters.

The recommended 5-stage pipeline:

```
Stage 1: Global Extraction (full novel → long-context pass)
  ├── Character registry (name, physical description, relationships)
  ├── Location registry (settings, visual atmosphere)
  ├── Narrative arc breakdown (acts, turning points)
  └── Story Bible document

Stage 2: Scene Segmentation (novel chapters → scene list)
  ├── Identify scene boundaries (location + time changes)
  ├── Classify each scene (action, dialogue, emotional, transition)
  └── Map scenes to narrative beats

Stage 3: Screenplay Adaptation (scene → screenplay)
  ├── Convert prose descriptions to observable actions
  ├── Adapt/compress dialogue for comic format (max ~35 words/bubble)
  └── Remove interiority — show don't tell

Stage 4: Panel Breakdown (screenplay scene → panel list)
  ├── Determine panel count per scene (3–8 panels)
  ├── Assign camera angle + framing per panel
  └── Write panel action descriptions

Stage 5: Image Prompt Generation (panel + story bible → prompt)
  ├── Inject character visual anchors (verbatim, always)
  ├── Apply style template
  └── Add camera/lighting/composition cues
```

### Long Context vs. RAG: The Hybrid Approach

A 300-page novel ≈ 120,000 tokens. This fits comfortably within Gemini 2.5 Pro (1M context) or Claude Opus 4.6 (1M context). Research shows long-context models outperform RAG on narrative understanding tasks — **56.3% vs 49.0%** accuracy on story QA benchmarks ([arXiv Dec 2024](https://arxiv.org/abs/2501.01880)).

However, making a full-novel API call for each of 600 panels would be prohibitively slow (30–60s per query vs. ~1s for RAG) and expensive. The optimal architecture is **hybrid** ([Redis benchmarks](https://redis.io/blog/rag-vs-large-context-window-ai-apps/)):

```
Phase 1: ONE long-context pass (Gemini 2.5 Pro)
  → Builds Story Bible, character registry, scene list
  → Costs ~$0.23

Phase 2: RAG index construction (once per novel)
  → Scene-boundary chunking (400–800 tokens/chunk)
  → Embed with text-embedding-3-small ($0.002)
  → Store in Qdrant (hybrid search: dense + BM25)

Phase 3: Per-panel generation (RAG, 600× per novel)
  → Retrieve relevant scene chunk + character descriptions
  → Inject Story Bible context
  → ~1s per query, ~800 tokens vs 120K full context
```

For long novels (500+ pages) or multi-book series, [RAPTOR](https://arxiv.org/abs/2401.18059) (hierarchical summarization trees) enables retrieval at different levels of abstraction. [GraphRAG](https://ragflow.io/blog/ragflow-support-graphrag) excels for relationship-heavy ensemble fiction (character relationship queries).

### Model Recommendations by Stage

| Stage | Model | Why |
|---|---|---|
| Global extraction | Gemini 2.5 Pro | 1M context, best for full-novel structural analysis |
| Screenplay writing | Claude Sonnet 4.6 | Best creative writing, follows instructions immediately ([Reddit comparison](https://www.reddit.com/r/WritingWithAI/comments/1rxdqu4/)) |
| Panel/prompt generation | Gemini 2.5 Flash | Fast, cheap ($0.30/M input), sufficient quality |
| Embeddings | text-embedding-3-small | Best price/quality for English narrative ($0.02/M tokens) |
| Vector store | Qdrant | Hybrid search, excellent metadata filtering |

### The Story Bible: Central Artifact

The Story Bible is a structured JSON document containing character visual anchors, location descriptions, and scene metadata. It is injected into every downstream LLM call. The **character visual anchor** — a fixed ~60–80 word physical description per character — is the single most impactful consistency technique. It must be used verbatim in every image prompt, never paraphrased.

Example:
```
"Tall woman, early 30s, sharp angular face, short black hair undercut,
 cold grey eyes, jagged scar across left cheek, dark tactical jacket
 with red arm patch, always composed posture. Same character, same appearance."
```

The phrase "Same character, same appearance" is a deliberate signal to image models to treat this as a continuity constraint ([OpenAI prompting guide](https://developers.openai.com/cookbook/examples/multimodal/image-gen-1.5-prompting_guide/)).

### LLM Pipeline Cost (300-page novel → 600 panels)

| Stage | Model | Cost |
|---|---|---|
| Global extraction | Gemini 2.5 Pro | $0.23 |
| Embeddings | text-embedding-3-small | $0.002 |
| Screenplay | Claude Sonnet 4.6 | $1.81 |
| Panel breakdown | Gemini 2.5 Flash | $0.27 |
| Image prompts | Gemini 2.5 Flash | $0.41 |
| **LLM Total** | | **~$2.72** |

The dominant cost is image generation ($1.20–$60 for 600 panels depending on model), not LLM text processing.

---

## 4. Video & Animation (Phase 2)

### Image-to-Video Models

> **⚠️ Sora 2 Status:** OpenAI announced full Sora shutdown on March 24, 2026. The app closes April 26, 2026; the API closes September 24, 2026. Sora is no longer viable for new pipeline development. The shutdown was driven by unsustainable costs (~$1M/day) and declining users. This reinforces the strategy of using cost-efficient models like Hailuo.

| Model | Cost/6s Clip | Max Duration | Character Consistency | API | Best For |
|---|---|---|---|---|---|
| Hailuo 02 Standard (MiniMax) | ~$0.27 (768p) | 6–10s | Good | Yes | Budget volume production |
| Hailuo 02 Pro (MiniMax) | ~$0.48 (1080p) | 6–10s | Good | Yes | Higher quality production |
| Runway Gen-4.5 | ~$1.20 | 10s | High | Yes | Cinematic quality |
| Kling 3.0 | ~$0.75 | 10s | Improved in v3.0 | Yes | Resolution + value |
| Veo 3.1 | ~$4.00 | ~8s | Good | Yes | Synchronized audio generation |

[Runway API docs](https://docs.dev.runwayml.com/guides/pricing/), [Kling 3.0 review](https://www.atlascloud.ai/blog/guides/kling-3.0-review-features-pricing-ai-alternatives), [Veo 3 pricing](https://www.gstory.ai/blog/veo-3-pricing/), [Hailuo 02 Fal.ai](https://fal.ai/models/fal-ai/minimax/hailuo-02/standard/image-to-video)

**Hailuo 02** remains the best value. The Standard tier via Fal.ai costs $0.045/sec at 768p ($0.27 for a 6-second clip). The Pro tier delivers native 1080p at $0.08/sec ($0.48 for 6 seconds). Ranked #2 globally on Artificial Analysis benchmarks. **Runway Gen-4.5** provides the highest quality and strongest character consistency within clips. **Veo 3.1** uniquely generates synchronized dialogue/SFX alongside video, potentially eliminating a separate lip-sync step.

### Open-Source Video

| Model | VRAM | Max Duration | Best For |
|---|---|---|---|
| LTX-2 (Lightricks) | 12GB+ | 30s | Best on consumer hardware, 18x efficiency |
| Wan 2.1 14B | 8–48GB | 12s | Multi-task, speed |
| HunyuanVideo-I2V | 80GB | 15s | Cinematic (requires H100) |
| AnimateDiff | 8GB+ | 3–6s | SD-based, style flexibility |

[Hyperstack comparison](https://www.hyperstack.cloud/blog/case-study/best-open-source-video-generation-models)

### Voice / TTS

| Tool | Cost | Voice Cloning | Quality | Best For |
|---|---|---|---|---|
| ElevenLabs Creator | $22/mo | Yes (30 clones) | Industry-leading | Character voices |
| OpenAI TTS | $15/1M chars | No (13 presets) | Good | Narration (4–5x cheaper) |
| XTTS v2 (open-source) | Infrastructure | Yes (6s reference) | Good | Self-hosted pipelines |

[ElevenLabs pricing](https://www.cekura.ai/blogs/elevenlabs-pricing), [OpenAI TTS pricing](https://costgoat.com/pricing/openai-tts)

### Lip-Sync

**Sync.so** is the clear choice for animating illustrated characters to speak — it explicitly supports cartoon/animated content at $0.05–$0.133/second with full API access ([Sync.so pricing](https://sync.so/pricing)).

### Episode Cost Estimates (15 minutes, 75 panels)

| Tier | Stack | Per Episode |
|---|---|---|
| Budget | Hailuo 02 Standard + OpenAI TTS + FFmpeg | ~$20–25 |
| Hybrid | Ken Burns + Sync.so lip-sync + ElevenLabs | ~$20–30 |
| Mid-tier | Kling 3.0 + ElevenLabs | ~$65–90 |
| Premium | Runway Gen-4.5 + ElevenLabs Pro | ~$120–200 |
| Self-hosted | Wan 2.1 + XTTS v2 (cloud GPU) | ~$15–25 |

---

## 5. Existing Projects & Lessons Learned

### What Already Exists

| Project | Approach | Consistency Solution | Limitation |
|---|---|---|---|
| [Dashtoon](https://techcrunch.com/2023/11/02/dashtoon/) | Commercial webtoon platform ($5M funded) | Custom character model training per user | Requires human creative direction |
| [LlamaGen.AI](https://llamagen.ai) | Full pipeline platform, KDP-ready | Proprietary LoRA + reference sheets | Less customizable |
| [AI Comic Factory](https://github.com/jbilcke-hf/ai-comic-factory) | Open-source LLM + SDXL | Prompt engineering + reference images | Limited cross-panel memory |
| [StoryDiffusion](https://github.com/HVision-NKU/StoryDiffusion) | NeurIPS 2024, 6,400 stars | Consistent Self-Attention (training-free) | Single-character focus |
| [DiffSensei](https://github.com/jianzongwu/DiffSensei) | CVPR 2025, manga-specific | MLLM-as-identity-adapter | B&W manga only |
| [DreamingComics](https://arxiv.org/html/2512.01686v1) | SOTA on ViStoryBench | LLM layout + video DiT | Research-stage |
| [n8n community pipeline](https://community.n8n.io/t/built-an-ai-pipeline-that-turns-text-into-full-comic-book-storyboards-feels-like-a-goldmine-but-i-need-some-discuss/225002) | No-code, Gemini agents | Character DB + visual anchors | Manual iteration |
| [Jenova Comic Creator](https://www.jenova.ai) | 6 style templates, plot memory engine | Reference sheet architecture | Newer platform |

### What the Community Has Learned

**What works ([Reddit community consensus](https://www.reddit.com/r/StableDiffusion/comments/1fp6g7q/)):**
- LoRA training is universally recommended as the most reliable consistency method (80–90%)
- The "edit from anchor, never regenerate" paradigm prevents cumulative drift
- Text/lettering must always be composited in post — AI text rendering is unreliable
- Shorter video clips (3–6s) maintain better consistency than longer ones
- Separate character generation + compositing beats multi-character single-pass generation
- Reference sheet systems (front/side/back views + key expressions) are now standard practice

**What doesn't work:**
- Prompt repetition alone is insufficient for reliable consistency
- ChatGPT/DALL-E sessions lose consistency context on timeout
- Stacking 3+ LoRAs (character + style + pose) causes VRAM conflicts
- Full end-to-end automation without human checkpoints produces "mechanical" output
- No tool handles 50+ panels with multiple characters reliably without drift ([Existing pipelines research](https://www.reddit.com/r/LocalLLaMA/comments/1qkmv6k/))

---

## 6. Recommended Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                     INPUT: Novel (EPUB/TXT/PDF)               │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 1: GLOBAL EXTRACTION          (Gemini 2.5 Pro, 1×)   │
│  Full novel → Story Bible JSON:                               │
│    • Character registry (visual anchors, relationships)       │
│    • Location registry (visual descriptions, atmosphere)      │
│    • Scene list with summaries, narrative beats               │
│  ► Human review checkpoint: approve Story Bible              │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 2: RAG INDEX + CHARACTER DESIGN  (parallel)           │
│                                                               │
│  Left track: Embed novel by scene → Qdrant hybrid index      │
│  Right track: Generate character reference sheets             │
│    (FLUX.2 Pro multi-ref or ComfyUI turnaround workflow)     │
│  ► Human review checkpoint: approve character designs         │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 3: SCREENPLAY     (Claude Sonnet 4.6, per scene)      │
│  Scene text (via RAG) + Story Bible → Screenplay format:     │
│    • Observable actions only (no interiority)                 │
│    • Compressed dialogue (≤35 words/bubble)                  │
│    • SFX annotations                                          │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 4: PANEL BREAKDOWN  (Gemini Flash, per scene)         │
│  Screenplay → Panel JSON array:                               │
│    • shot_type, camera_angle, characters_present              │
│    • character_actions, expressions, positions                │
│    • background, lighting, mood, dialogue                    │
│    • 3–8 panels per scene                                    │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 5: IMAGE PROMPTS    (Gemini Flash, per panel)         │
│  Panel JSON + Story Bible → Structured prompt:               │
│    [STYLE TEMPLATE]  ← fixed for entire project              │
│    [LOCATION ANCHOR] ← from location registry                │
│    [CHARACTER ANCHORS] ← verbatim from Story Bible           │
│    [ACTION / CAMERA / MOOD]  ← from panel JSON               │
│    "No text. No speech bubbles. Single panel only."          │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 6: IMAGE GENERATION  (FLUX.2 Pro or SDXL + LoRA)     │
│  Prompt + character reference images → Panel image           │
│    • FLUX.2 multi-ref: 4–8 anchor images per call            │
│    • OR: SDXL + LoRA + IP-Adapter + ControlNet (ComfyUI)    │
│  Post-processing: ADetailer, Real-ESRGAN upscale            │
│  ► Human review checkpoint: approve panels per chapter       │
└───────────────────────────┬──────────────────────────────────┘
                            ▼
┌──────────────────────────────────────────────────────────────┐
│  STAGE 7: ASSEMBLY                                            │
│  Panel images + dialogue text → Comic pages                  │
│    • Layout engine (Pillow/Cairo or Remotion)                │
│    • Speech bubble + caption overlay (post-composited)       │
│    • Export: PDF (print), EPUB (digital), CBZ (reader)       │
└──────────────────────────────────────────────────────────────┘

         ╔═══════════════════════════════════════╗
         ║  PHASE 2 (FUTURE): ANIMATION          ║
         ║  Panel images → I2V (Hailuo/Kling)    ║
         ║  + TTS (ElevenLabs)                    ║
         ║  + Lip-sync (Sync.so)                  ║
         ║  + Assembly (FFmpeg)                    ║
         ║  → Episode MP4                         ║
         ╚═══════════════════════════════════════╝
```

### Tech Stack

| Component | Recommended | Alternative |
|---|---|---|
| **Orchestration** | Python + LangGraph | n8n (no-code) |
| **LLM (extraction)** | Gemini 2.5 Pro API | Claude Opus 4.6 |
| **LLM (screenplay)** | Claude Sonnet 4.6 API | GPT-5.x |
| **LLM (panels/prompts)** | Gemini 2.5 Flash API | GPT-5 mini |
| **Embeddings** | text-embedding-3-small | Voyage-3 |
| **Vector store** | Qdrant (self-hosted Docker) | Chroma (prototyping) |
| **Image generation** | FLUX.2 Pro via Together AI | SDXL + LoRA (ComfyUI) |
| **Image prototyping** | FLUX.2 [klein] 4B (local or Fal.ai) | SDXL via Together AI |
| **Comic assembly** | Pillow + Python | Remotion (React) |
| **Animation** | Hailuo 02 API (Standard or Pro) | Kling 3.0 API |
| **TTS** | ElevenLabs Creator | OpenAI TTS |
| **Lip-sync** | Sync.so API | LatentSync (open-source) |
| **Video assembly** | FFmpeg | MoviePy |

### Total Cost Estimates (300-page novel)

| Output | Budget | Standard | Premium |
|---|---|---|---|
| LLM pipeline | ~$0.80 | ~$2.72 | ~$15 |
| 600 comic panels | ~$1.20 (self-hosted) | ~$18–24 (FLUX.2 Pro) | ~$60 (GPT Image HD) |
| Comic assembly | $0 | $0 | $0 |
| **Comic total** | **~$2–5** | **~$25–35** | **~$75–100** |
| Animation (15-min ep) | +$15–25 | +$65–90 | +$120–200 |
| **Comic + Animation** | **~$20–30** | **~$90–125** | **~$200–300** |

### Implementation Phases

**Phase 1 (Weeks 1–2): Proof of Concept**
- Pick a public domain short story (10–20 pages)
- Implement Stages 1–5 as a Python script with Gemini + Claude APIs
- Generate 10–15 panels using FLUX.2 Pro API with multi-reference
- Manually assemble into a comic page
- Goal: validate the pipeline works end-to-end

**Phase 2 (Weeks 3–4): Core Pipeline**
- Build the RAG index (Qdrant + text-embedding-3-small)
- Build the Story Bible JSON schema and extraction prompts
- Build the prompt assembly engine (style template + character anchors + panel JSON → image prompt)
- Test on a full novel chapter (30–50 panels)
- Goal: one chapter produced with minimal manual intervention

**Phase 3 (Weeks 5–8): Consistency & Quality**
- Experiment with LoRA training vs. multi-reference for character consistency
- Build the comic page layout engine (panel arrangement, speech bubble overlay)
- Add human-in-the-loop review checkpoints (Story Bible, character designs, chapter review)
- Export to PDF/EPUB/CBZ
- Goal: produce a full 150-panel comic chapter at acceptable quality

**Phase 4 (Future): Animation**
- Add Hailuo 02/Kling image-to-video for panel animation
- Add ElevenLabs TTS for narration/dialogue
- Add Sync.so lip-sync for talking character panels
- FFmpeg assembly into episodes
- Goal: 10–15 minute animated episode from comic panels

### Key Design Principles

1. **Schema-first**: the Story Bible JSON schema enforces consistency without relying on model memory — it is the continuity system
2. **Character anchors are sacred**: never paraphrase, always inject verbatim
3. **Decompose relentlessly**: each LLM call does exactly one thing
4. **Edit, don't regenerate**: always work from the original character anchor, never from the previous panel's output
5. **Text in post**: speech bubbles and captions are composited programmatically, never generated inside images
6. **Human checkpoints at boundaries**: automate within scenes, review at chapter transitions
7. **No negative prompts for FLUX**: FLUX.2 uses positive-only architecture — describe what you want, not what to avoid

---

## 7. Phase 1 Implementation: Getting Started

This section provides concrete starting points for the proof-of-concept.

### Suggested PoC Source Material

Choose a public domain short story with:
- 2–4 distinct characters (to test multi-character consistency)
- 2–3 distinct locations (to test environment plates)
- A mix of dialogue and action scenes
- Good candidates: H.G. Wells short stories, O. Henry, Edgar Allan Poe, Grimm's fairy tales

### Story Bible JSON Schema (Draft)

```json
{
  "title": "Story Title",
  "style": {
    "template": "Bold graphic novel, cel-shaded, high contrast shadows, limited color palette, thick ink outlines",
    "aspect_ratio": "3:4",
    "resolution": "1024x1344"
  },
  "characters": [
    {
      "id": "char_001",
      "name": "Elena Vasquez",
      "visual_anchor": "Tall woman, early 30s, sharp angular face, short black hair undercut, cold grey eyes, jagged scar across left cheek, dark tactical jacket with red arm patch, always composed posture. Same character, same appearance.",
      "reference_images": ["refs/elena_front.png", "refs/elena_34.png", "refs/elena_side.png", "refs/elena_action.png"],
      "relationships": {"char_002": "partner", "char_003": "antagonist"},
      "first_appearance": "scene_001"
    }
  ],
  "locations": [
    {
      "id": "loc_001",
      "name": "The Bunker",
      "visual_anchor": "Underground concrete bunker, dim fluorescent lighting, exposed pipes on ceiling, military equipment racks along walls, single metal table in center, cold blue-grey tones.",
      "plate_image": "plates/bunker.png"
    }
  ],
  "scenes": [
    {
      "id": "scene_001",
      "chapter": 1,
      "location": "loc_001",
      "characters": ["char_001", "char_002"],
      "summary": "Elena briefs her partner on the mission.",
      "type": "dialogue",
      "source_text_range": [0, 2400]
    }
  ]
}
```

### Minimal PoC Script Structure

```
novel_to_comic/
├── config.py              # API keys, model choices, paths
├── stage1_extraction.py   # Novel → Story Bible JSON
├── stage2_rag.py          # Build Qdrant index + generate character refs
├── stage3_screenplay.py   # Scene → screenplay format
├── stage4_panels.py       # Screenplay → panel JSON array
├── stage5_prompts.py      # Panel JSON + Story Bible → image prompts
├── stage6_generate.py     # Image prompts → panel images (FLUX.2 API)
├── stage7_assembly.py     # Panel images + dialogue → comic pages
├── story_bible.json       # Central artifact (generated by stage 1)
├── prompts/               # System prompts for each LLM stage
│   ├── extraction.txt
│   ├── screenplay.txt
│   ├── panel_breakdown.txt
│   └── image_prompt.txt
└── output/
    ├── panels/            # Individual panel images
    ├── pages/             # Assembled comic pages
    └── exports/           # PDF/EPUB/CBZ
```

---

## Sources

All citations are inline throughout the document. Key primary sources:

- [BFL FLUX.2 Documentation & Pricing](https://docs.bfl.ml/quick_start/pricing)
- [BFL FLUX.2 Prompting Guide](https://docs.bfl.ml/guides/prompting_guide_flux2)
- [BFL FLUX.2 Klein](https://bfl.ai/models/flux-2-klein)
- [Together AI FLUX.2 Multi-Reference](https://www.together.ai/blog/flux-2-multi-reference-image-generation-now-available-on-together-ai)
- [DSR: Decomposed Screenwriting (EMNLP 2025)](https://arxiv.org/html/2510.23163v3)
- [Long Context vs RAG (arXiv 2024)](https://arxiv.org/abs/2501.01880)
- [StoryDiffusion (NeurIPS 2024)](https://arxiv.org/html/2405.01434v1)
- [DreamingComics (arXiv 2025)](https://arxiv.org/html/2512.01686v1)
- [OpenAI Image Generation Prompting Guide](https://developers.openai.com/cookbook/examples/multimodal/image-gen-1.5-prompting_guide/)
- [RAPTOR Hierarchical RAG (ICLR 2024)](https://arxiv.org/abs/2401.18059)
- [n8n Community Comic Pipeline](https://community.n8n.io/t/built-an-ai-pipeline-that-turns-text-into-full-comic-book-storyboards-feels-like-a-goldmine-but-i-need-some-discuss/225002)
- [StoryBlender (arXiv March 2026)](https://arxiv.org/html/2604.03315v1)
- [Sora Shutdown Announcement (March 24, 2026)](https://x.com/soraofficialapp/status/2036546752535470382)
- [Hailuo 02 via Fal.ai](https://fal.ai/models/fal-ai/minimax/hailuo-02/standard/image-to-video)
- [LlamaGen.AI](https://llamagen.ai)
- [Jenova Comic Creator](https://www.jenova.ai/en/resources/ai-comic-panel-creator)

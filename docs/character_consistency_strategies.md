# Canary Pipeline: Strategies for Character Consistency

This document outlines four technical architectures for achieving character consistency across panels in the Canary pipeline. Because Canary relies entirely on cloud APIs (no local GPUs), the chosen approach must balance API capabilities, compute costs, and architectural complexity.

## 1. Zero-Shot Face Injection (PuLID via Serverless API)
*This approach uses advanced adapters (like PuLID) to inject a character's facial embeddings directly into the diffusion process during generation.*

### Architecture Impact
*   **Stage 2:** Must be updated to guarantee `front.png` is a tight, high-resolution, unobstructed headshot.
*   **Stage 6 / Clients:** Add a new router in `clients/flux.py` to hit a dedicated serverless GPU endpoint (e.g., Replicate `lucataco/flux-pulid`). The reference image is passed as a base64 payload alongside the text prompt.

### Economics & Performance
*   **Cost:** High. Requires A100/H100 compute time per image. ~$0.04 to $0.06 per panel.
*   **Speed:** ~15-20 seconds per panel.

### Pros & Cons
*   **Pros:** Requires no upfront training; zero-shot consistency; perfect facial identity.
*   **Cons:** **The Multi-Character Bottleneck.** Standard PuLID APIs only accept one `main_face_image`. Panels with 2+ characters will result in blended "chimera" faces or the wrong face on the wrong body.

---

## 2. On-the-Fly LoRA Training (The Production Standard)
*Instead of zero-shot injection, the pipeline pauses to actually train the image model on the character's face and outfit before generating panels.*

### Architecture Impact
*   **Stage 2:** Must generate 5-10 varied images of the character (front, side, action, various expressions).
*   **New Stage (2.5):** Call a training API (Fal.ai, Together AI) uploading the images. Wait for the API to return a `lora_id` (e.g., `lora_hero_123`). Store this in the `StoryBible`.
*   **Stage 6:** Standard generation calls, but injecting `<lora:hero_123:0.8>` into the prompt or API payload.

### Economics & Performance
*   **Cost:** Medium overall, but front-loaded. ~$1.00 to $2.00 to train the LoRA per character. Panel generation remains cheap (~$0.003 to $0.03).
*   **Speed:** Pipeline pauses for ~3 to 5 minutes per character at Stage 2.5. Panel generation is fast.

### Pros & Cons
*   **Pros:** The highest possible quality. The model understands the character in 3D space, handles extreme poses/lighting, and **solves the multi-character problem** (APIs like Fal support loading multiple LoRAs per request).
*   **Cons:** High upfront cost and wait time before the user sees the first panel.

---

## 3. Post-Generation Face Swapping (The Decoupled Approach)
*Allow the base text-to-image model to generate random faces, then use a dedicated facial-recognition API to swap them out in post-production.*

### Architecture Impact
*   **Stage 6:** Requires a two-step process. 
    1. Generate the panel normally via Together/Gemini.
    2. If characters are present, call a Face Swap API (e.g., InsightFace on Replicate), passing the generated panel and the character's `front.png`.

### Economics & Performance
*   **Cost:** Very low. Face swap APIs are highly optimized. <$0.01 per swap.
*   **Speed:** Adds ~2-3 seconds to panel generation time.

### Pros & Cons
*   **Pros:** Cheap, fast, and **handles multiple characters perfectly** (run the swap sequentially for every face detected in the panel).
*   **Cons:** Only fixes the face, not the outfit (outfits must still rely on text prompts). Swaps can sometimes look "pasted on" if the lighting or angle is extreme.

---

## 4. Strict Tag Anchoring (The Zero-Cost Optimization)
*Enhance Canary's current method by optimizing how the LLM writes the `visual_anchor`, tailoring it specifically for how diffusion models parse text.*

### Architecture Impact
*   **Stage 1:** Modify the extraction prompt. Instead of prose ("A tall man wearing a red coat..."), force the LLM to output a strict, comma-separated list of Danbooru-style tags: `1boy, tall, red coat, black hair, green eyes`.
*   **Stage 6:** No changes required. The optimized tags are injected into the image prompts.

### Economics & Performance
*   **Cost:** Zero additional cost.
*   **Speed:** Zero additional time.

### Pros & Cons
*   **Pros:** Keeps the pipeline completely API-agnostic, fast, and free.
*   **Cons:** "Style consistency" rather than "Identity consistency." The character will look like the same *type* of person, but facial features will drift between panels.

---

## Recommendation for Canary MVP

Given Canary's architecture (discrete, resumable stages and a focus on minimizing iteration costs via `dev_mode`):

**Short Term:** Implement **Route 4 (Strict Tag Anchoring)**. It requires only prompt engineering in Stage 1 and immediately improves output without adding fragile API dependencies or breaking multi-character panels.

**Long Term (Product Release):** Implement **Route 2 (On-the-Fly LoRA)**. While it introduces a waiting period, it is the only professional-grade solution that reliably handles multi-character interactions (Hero punching Villain), which is mandatory for comic books. The upfront cost ($2) is justifiable for a user rendering an entire novel, and because Canary's `state.json` makes stages resumable, the training time can happen asynchronously.
# Canary Character Consistency: A/B Testing Plan

This document outlines the engineering plan to empirically test the top two character consistency architectures (PuLID vs. LoRA) without disrupting the main Canary pipeline.

## Objective
Generate a side-by-side visual comparison of a single-character panel and a multi-character panel using three different backends:
1.  **Baseline:** Current Together AI (FLUX) with Strict Tagging.
2.  **Route 1:** Replicate API (FLUX + PuLID adapter).
3.  **Route 2:** Fal.ai API (On-the-fly LoRA training + FLUX).

This will identify the exact compute costs, generation latency, and (crucially) how each architecture handles the \"chimera\" blending problem when two characters are in the same panel.

---

## Prerequisites
*   A fully processed sample project (e.g., `projects/one-of-these-days`) that has completed Stage 5 (Prompts).
*   A valid Replicate API key (for PuLID).
*   A valid Fal.ai API key (for LoRA).

---

## Test Subject Selection
We will manually select two prompt files from `projects/{project}/prompts/` to use as our constant variables:
1.  **Subject A (Single Character):** A panel featuring only the protagonist (e.g., `char_001`).
2.  **Subject B (Multi-Character):** A panel featuring the protagonist and a second character (e.g., `char_001` and `char_002`) interacting in the same frame.

---

## Script 1: Testing Replicate PuLID (`scripts/test_replicate_pulid.py`)

**Goal:** Test zero-shot face injection.

**Implementation Steps:**
1.  **Input:** Takes a scene prompt JSON and the `projects/{project}/refs/char_001/front.png` reference image.
2.  **Execution:** Makes a pure `httpx` POST request to `https://api.replicate.com/v1/models/lucataco/flux-pulid/predictions`.
3.  **Payload constraints:**
    *   `prompt`: The text prompt from the JSON.
    *   `main_face_image`: The base64 encoded `front.png`.
4.  **Multi-Character Test:** For Subject B, we will attempt to pass *two* images if the endpoint allows, or pass the protagonist's face and observe if the API erroneously applies it to both characters in the panel.
5.  **Output:** Saves the images to `projects/{project}/tests/pulid_single.png` and `pulid_multi.png`. Records latency and API cost.

---

## Script 2: Testing Fal.ai LoRA (`scripts/test_fal_lora.py`)

**Goal:** Test on-the-fly training and multi-LoRA inference.

**Implementation Steps (Phase A: Training):**
1.  **Input:** Takes the directory `projects/{project}/refs/char_001/` (containing front, side, action shots).
2.  **Execution:** Uploads the images to Fal.ai's storage, then calls the `/fal-ai/flux-lora-fast-training` endpoint.
3.  **Payload constraints:** Sets `trigger_word` to \"canary_char_001\".
4.  **Wait:** Polls the endpoint until training completes (~3-5 minutes) and retrieves the resulting `lora_url`.
5.  *(Optional but recommended): Repeat the training phase for `char_002` to test multi-character integration properly.*

**Implementation Steps (Phase B: Inference):**
1.  **Execution:** Calls Fal.ai's `/fal-ai/flux-lora` inference endpoint.
2.  **Payload constraints:**
    *   `prompt`: The text prompt from the JSON, explicitly modified to include the trigger word(s) (e.g., \"canary_char_001 punches canary_char_002\").
    *   `loras`: A list of the trained `lora_url`s.
3.  **Output:** Saves the images to `projects/{project}/tests/lora_single.png` and `lora_multi.png`. Records latency and total API cost (Training + Inference).

---

## Evaluation Metrics (The A/B Comparison Matrix)

After the scripts run, the developer will manually review the 6 output images (Baseline, PuLID, LoRA x Single, Multi) and evaluate them against these criteria:

| Metric | Baseline (Tags) | Route 1 (PuLID) | Route 2 (LoRA) |
| :--- | :--- | :--- | :--- |
| **Facial Identity Match** | 1-10 score | 1-10 score | 1-10 score |
| **Outfit/Body Consistency** | 1-10 score | 1-10 score | 1-10 score |
| **Multi-Character Bleed** | Did traits mix? | Did traits mix? | Did traits mix? |
| **Generation Latency** | ~3s | Time recorded | Time recorded |
| **Total Cost per Panel** | ~$0.03 | Cost recorded | Cost recorded |
| **Upfront Friction** | None | None | ~5 min wait |

---

## Next Action
To execute this plan, the developer needs to:
1. Approve the creation of the two test scripts in the `scripts/` directory.
2. Provide Fal.ai and Replicate API keys in the `.env` file.
3. Run the scripts against an existing Canary project.

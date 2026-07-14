---
target: current style suggestions and proofs generation pipeline
total_score: 21
p0_count: 0
p1_count: 5
timestamp: 2026-07-13T20-43-41Z
slug: web-src-pages-rooms-styleroom-tsx
---
Method: dual-agent (A: /root/design_review · B: /root/detector_browser)

# Design Health Score

| # | Heuristic | Score | Key issue |
|---|---|---:|---|
| 1 | Visibility of system status | 3 | Progress exists, but per-proof state is not announced and some claims are inaccurate. |
| 2 | Match system / real world | 3 | Art-direction language is strong; the mystery details glyph and raw prompt prose weaken it. |
| 3 | User control and freedom | 2 | No direct brief/reference path; completed proofs freeze during new suggestions. |
| 4 | Consistency and standards | 2 | Card-as-button semantics and mixed localization create inconsistent behavior. |
| 5 | Error prevention | 2 | Credit confirmation is good; load failures can masquerade as an empty prerequisite state. |
| 6 | Recognition rather than recall | 2 | Decision-critical descriptions are clamped and full details live in a modal. |
| 7 | Flexibility and efficiency | 1 | One fixed five-proof path; no direct, one-proof, or shortlist workflow. |
| 8 | Aesthetic and minimalist design | 2 | Strong brand system, but a dense wall of small uniform proofs impedes judgment. |
| 9 | Error recovery | 2 | Per-proof retry exists; page-load and suggestion failures lack strong recovery. |
| 10 | Help and documentation | 2 | Good section copy, but no visible explanation of why a direction fits the story. |
| **Total** | | **21/40** | **Acceptable; significant improvements needed** |

# Anti-patterns verdict

The interface does not read like a generic AI SaaS shell; it uses the established pressroom system and canonical composites. The automated detector found zero signature anti-patterns in `StyleRoom.tsx`. The problem is task design, not visual slop: the gallery becomes a uniform wall of 4:5 cards, hides the evidence needed to choose, and offers only one expensive generation path.

No reliable live overlay was produced. The protected route redirected to `/login`, so browser evidence was limited to the auth gate and source inspection.

# Overall impression

The strongest opportunity is to turn this from a batch-results gallery into a real art-direction checkpoint: let authors state intent before spending, generate a deliberately curated portfolio, and present the resulting proofs as stable, comparable evidence.

# What is working

- Story-specific proof content, per-proof regeneration, credit confirmation, asynchronous progress, and the standing approval bar are good foundations.
- The selected direction is clearly named and downstream use is explained.
- The room uses the canonical `EntityCard`, `RoomHeader`, `SectionHeader`, and `ApprovalBar` components.

# Priority issues

## P1 — The proof compiler likely contradicts its own subject brief

`generate_sample_image()` puts the character only in freeform `visual_brief`, leaving structured `subjects` empty. The shared compiler then emits `exactly 0 characters`. Fix the proof input contract so the selected character/location are structured anchors/subjects, and add a regression test over the final compiled prompt.

Suggested command: `$impeccable harden` for surfaced state; backend fix requires normal engineering work.

## P1 — The suggestion engine optimizes medium novelty, not graphic-novel fitness

The LLM sees title, author, optional style notes, and an unordered set of scene types mislabeled as genre/tone. It does not receive story summaries, arcs, themes, visual motifs, emotional range, or audience. Diversity is checked only through declared medium token overlap, and the first five of eight are retained even when diversity constraints were stated across all eight.

Fix: create a compact story art-direction brief; return structured axes and suitability rationale; score for sequential-art legibility, repeatability, environment/action range, value/color separation, source fit, and model feasibility; then select a portfolio with explicit palette and rendering distance.

Suggested command: `$impeccable shape` for the decision contract.

## P1 — There is no author-directed starting lane

The only route generates five more descriptions and five images. Add two first-class lanes before spend: **Art-direct for me** and **Bring a direction**. The second accepts text, image, or both, shows the interpreted visual attributes, and can generate one faithful proof or a curated neighborhood of alternatives.

Suggested command: `$impeccable shape`.

## P1 — The proof format creates the gray wall

Every style receives the same quiet portrait, directional light, and bright-accent/deep-shadow instruction. This fairly controls content, but it also controls tonal structure and tests portrait rendering more than sequential storytelling. Use a staged audition: a story-specific keyframe with neutral scene facts and candidate-owned color/lighting, followed by a richer validation proof for shortlisted styles (character expression, environment/action, and continuity).

Suggested command: `$impeccable bolder` for presentation; backend proof design requires normal engineering work.

## P1 — The comparison UI hides and moves decision evidence

Candidate prose is clamped to three lines, the full direction is hidden behind a cryptic image icon, cards can shrink to 220px, and selection moves a card out of its original position. Keep all five in stable order, use a two-up comparison gallery, expose structured attributes and “why it fits,” allow inline expansion, and use a real radio/select control. Promote the choice only after confirmation.

Suggested command: `$impeccable layout` and `$impeccable clarify`.

# Persona red flags

- **Jordan, first-time indie author:** cannot explain an existing vision, cannot tell why a suggestion fits, and must interpret truncated art-director prose.
- **Sam, keyboard/screen-reader user:** the selected card loses coherent pressed/checked semantics, the nested details button is confusing, status is not live-announced, and modal focus management is incomplete.
- **Mara, deliberate author/art director:** cannot upload a moodboard or request one proof, loses spatial memory when selection reorders the gallery, and pays for five rendered options even when only one direction is relevant.

# Minor observations

- The UI drops the stored `medium` field, despite medium being the backend's only explicit diversity dimension.
- Lettering introduces a second decision before the style decision is closed; collapse it behind “Matched automatically” or defer customization.
- Multiple core strings bypass i18n despite the en/es/fr commitment.
- Cache validity ignores brief-prompt/model version, proof freshness uses file existence rather than request fingerprint, and positional indices stand in for stable suggestion IDs.
- Requiring named real artists/publications as anchors creates product/IP risk and is not necessary; translate references into observable visual attributes instead.

# Questions to consider

1. Should a supplied direction produce one faithful candidate plus four neighbors, or make all five variations of that direction?
2. Should users be allowed to approve a single custom proof without generating a batch?
3. Is the desired portfolio four reliable launch-ready directions plus one controlled wildcard, or a more experimental set overall?

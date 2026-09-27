# Scenewright v3 showcase set

September 26, 2026 · Remotion compositions in `src/v3/` · 30 fps

v3 replaces the v2 "Any style" promo for public use. v2 is kept for comparison only: its opening, lettering, revision and page-wall sections use *Dungeon Crawler Carl* and *The Egg*, which are not cleared for public campaigns.

## Compositions

| Id | Size | Length | Use |
|---|---|---|---|
| `V3Hero` | 1920 × 1080 | 66 s | Landing page, YouTube, Product Hunt, pitches |
| `V3Ad30` | 1920 × 1080 | 30 s | YouTube in-stream, X, LinkedIn |
| `V3Teaser916` | 1080 × 1920 | 15 s | Reels, TikTok, Shorts; keeps clear of the bottom 17% and right-edge controls |
| `V3Teaser45` | 1080 × 1350 | 15 s | Instagram and Facebook feed |
| `V3Bumper169`, `V3Bumper916`, `V3Bumper11` | 16:9, 9:16, 1:1 | 6 s | YouTube bumpers, stories, retargeting |
| `V3LandingLoop` | 800 × 1000 | 10 s, silent loop | Replacement for the landing hero loop (`web/public/marketing/hero-flipbook.mp4`) |

Render: `npx remotion render <Id> out/v3/<name>.mp4 --codec=h264 --crf=18`

Final renders (September 26, 2026) in `out/v3/`: `scenewright-hero-66s-16x9.mp4` (66.05 s), `scenewright-ad-30s-16x9.mp4`, `scenewright-teaser-15s-9x16.mp4`, `scenewright-teaser-15s-4x5.mp4`, `scenewright-bumper-6s-{16x9,9x16,1x1}.mp4`, and `landing-loop-web.mp4` (600 px, 2.5 MB, with `landing-loop-poster.webp`). All are H.264 with 48 kHz AAC except the silent loop. The hero decodes without errors (mean −15.8 dB, peak −3.1 dB); every cut was reviewed from frame strips.

## Sources and rights

Every frame is real project output from these sources only:

| Source | Rights | Used for |
|---|---|---|
| *The Masque of the Red Death*, Edgar Allan Poe (1842) | Public domain | Opening manuscript, flipbook proofs, hero edition |
| *The Call of Cthulhu*, H. P. Lovecraft | Public domain | "Describe the look", "Or show it a picture", integrated lettering, public reader |
| *Kaitlin Out of Space*, Krishan Coupland | CC0 1.0 | "Or ask for six ideas", cast continuity, whole-book fallback |
| *Site-30's Janitor*, JanitorCakeworth, SCP Wiki | CC BY-SA 3.0 | Three editions, both lettering modes; credited on screen. Pages 1–3 only |
| *The Terror* (Maupassant), *The Lady, or the Tiger?* (Stockton) | Public domain | Proof wall and page wall |

Excluded on purpose: Kaitlin pages 4 and 8 (narration over faces), 11 (speech balloon without a tail) and 20 (undressing); Janitor pages 4 onward (gore); the last panel of the Janitor gouache page 1 (profanity) is cropped out of every close-up; Cthulhu proof 6, whose direction was built from an uploaded Dungeon Crawler Carl page.

On-screen style names describe the medium. They never repeat an artist's name, even where the project's own suggestion label does.

## New production for this set

Authorized by the owner on September 26, 2026, with text stages on Claude Opus 5.5 (Claude Code adapter) and images on GPT-5.5 (Codex adapter). These development adapters are never shown or described in the media.

- **The Masque of the Red Death** (`ee8c41ee-…`): imported from the archive catalogue as an editable-lettering project. Opus 5.5 wrote a brief that keeps plague imagery restrained (scarlet stains and silhouettes, no gore). Six suggested directions came from "ask for six"; 23 author directions were typed through the real *Bring a direction* composer, one medium each and no artist names. The edition uses proof 4 (woodblock print).
- **Omitted proofs:** 12 ("cozy children's picture book in soft watercolor") rendered as a realistic painting; 19 ("neon synthwave noir") has the rain reflections but no neon palette; 29 ("ink-and-wash brush painting") came back as a color painting. They are left out rather than relabeled. Proof 27 ("cross-stitch sampler") failed at the provider and was not retried. The flipbook shows the remaining 25 directions; the edition uses proof 4.
- **Masque edition:** 24 pages drawn in the woodblock look, with a restrained brief (scarlet stains and silhouettes). Pages 1–2 and 16–24 show plague victims or the blood-spattered masked figure, so they stay out of ads; the film shows them only as thumbnails on the page wall.
- **Plain-words revision:** page 3, "Change Prospero's red inner robe and lining to deep violet in both panels…" (exact text in `src/v3/revision.ts`). Render 2 was checked visually: violet in both panels, with face, pose, procession and layout unchanged. Two earlier attempts produced no image and are not shown. A page 10 gown-colour request was silently declined by the provider's safety system. The first page 3 attempt hit a transport disconnect; the Codex image store confirmed no image existed before the single manual resubmission.
- **Elm and Keep** (`68434034-…`, CC0, @strnglft): imported to give the showcase a fantasy title for the largest author segment. Its six proofs are on the proof wall; the edition uses proof 1 (Franco-Belgian clear line). Cast approved; its pages were still in production when these renders were made, so they are not on the page wall yet. Re-run `prepare-v3.py` and re-render `V3Hero` once they are drawn and their lettering is reviewed.

## Lettering cleanup before capture

Editable lettering was reviewed and fixed in the real editor API before any capture. Each page was checked visually as a composite, then saved with `mark_reviewed`.

- Site-30's Janitor (gouache) pages 1–3, lettering revision 4: the three intercom lines use the "radio" voice (electric balloon; offscreen voices take no tail); tails aimed at mouths; the page 1 panel 5 balloon and the page 3 panel 2 balloon moved off the speakers' heads.
- The Masque of the Red Death pages 1–24: every page checked as a composite. Captions moved off faces on pages 2 and 3; Prospero's balloons on pages 15 and 19 re-aimed at his mouth, and the page 19 balloon moved so its tail no longer crosses his eye.
- Uncommitted lettering-model work in the checkout later changed the lettering hash, so these saved pages currently fail validation (see [findings](../FINDINGS-2026-09-26.md) #14). The videos use composites rendered before that change; re-stamp before Finish or export.
- Kaitlin Out of Space can't be edited without rerunning Plan (see [findings](../FINDINGS-2026-09-26.md) #2), so only its already-clean pages appear up close.

## Sound

`scripts/make-score-v3.py` writes one original score per cut to `public/v3/audio/` (120 BPM, D minor, no samples), reusing the v2 instruments. Cues follow each timeline; every cut is mastered to −14 LUFS with peaks under −1 dBFS. Run it with an environment that has numpy, scipy, soundfile and pyloudnorm.

## Rebuild

1. `python3 scripts/prepare-v3.py` copies project art into `public/v3` and writes `src/v3/assets.generated.ts`.
2. `<audio python> scripts/make-score-v3.py` regenerates the scores.
3. Render the compositions above.

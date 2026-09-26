# Scenewright promo: "Your novel. Any style."

**Status: Historical.** This records a local production. Only this document is
tracked; the video project, source media, and renders are local-only and are not
part of repository CI. Rebuild commands below require that local project.

September 22, 2026 · 1920 × 1080 · 30 fps · 65 seconds · composition `ScenewrightAnyStyle`

Final render: `out/scenewright-any-style-revised.mp4`

To rebuild: `npx remotion render ScenewrightAnyStyle out/scenewright-any-style-revised.mp4 --codec=h264 --crf=18 --concurrency=2`

The final export was checked on September 22, 2026: 1920 × 1080 H.264 at 30 fps, 65.045 seconds, 48 kHz stereo AAC, no decode errors, continuous audio (mean −15.8 dB, peak −2.8 dB). Full-resolution frames and a timeline contact sheet were reviewed for copy, Cthulhu assets, label spacing, and the closing wordmark.

## Directed revision of the 65-second cut

The Opus composition remains the source of this film. Its rapid style showcase now says **“Any style you imagine. As many as you want.”** The proof count stays off screen so the sequence conveys creative freedom rather than a finite catalog. From 14 seconds onward, the direction, proof exploration, selected look, finished book, cast, and integrated lettering examples come from **The Call of Cthulhu**. The brief Carl page revision remains later as a distinct example. The comparison at 30 seconds now follows one selected Cthulhu direction through its finished edition, avoiding the impression of an instant style switch. The 59-second page wall keeps its central line and drops the count. The closing mark pairs the approved vector symbol with live Anybody text, avoiding the fallback font in the old SVG lockup.

## What changed from the 41-second cut

The earlier cut showed two preset proofs side by side and read as "choose between two styles". This cut leads with the differentiator: **any look, from your own words or your own picture, carried through a whole book**. Everything on screen is real project output or a real UI recording from this account. Credits, costs and the development model routing are never shown.

## Timeline (120 BPM; one beat = 15 frames)

| Time | Section | Real source |
| --- | --- | --- |
| 0–4 s | "Your novel." Manuscript passage; five details get highlighted | `dcc1-2/input/dcc1.txt`, the lines that open the snow scene |
| 2–4 s | "Your comic." The page lands panel by panel; each highlighted detail pins to its drawing | `dcc1-2` style proof 11 (the author's reference-built look) |
| 4–11 s | "Any style." The same page flips through every proof, accelerating | `dcc1-2` style proofs: the original 11 plus new author directions typed into the real composer |
| 11–14 s | "Any style you imagine. As many as you want." Wall of the project's style proofs | Same; all proofs are specific to this scene |
| 14–18 s | "Describe it." A Cthulhu art-direction note types on, then its proof lands | Real note from `the-call-of-cthulhu/samples/style_suggestions.json`; matching style proof 2 |
| 18–22 s | "Show it." Real upload + note in the Cthulhu project → proof | Upload is a crop of pixel-art Carl page 26; proof `the-call-of-cthulhu/samples/style_6.png` |
| 22–26 s | "Keep creating." Cthulhu directions made for that project | Real Cthulhu style proofs 1–6, accumulated through author input and generated suggestions; they are not presented as one batch |
| 26–34 s | "Choose a look." Author reference and selected proof → finished 44-page Cthulhu edition | `the-call-of-cthulhu` style proof 1 and finished pages; the active project style matches proof 1 |
| 34–38 s | "Same faces. Every page." | Cthulhu's Thurston and Wilcox approved reference sheets; close-ups from finished pages 2, 5, 24, 25, 26, 29 |
| 38–48 s | "Two ways to letter." Integrated Cthulhu lettering; The Egg's editable lettering and translations | Cthulhu pages 3, 16, 40; editor recording on The Egg page 21; project translations EN/ES/FR |
| 48–52 s | "Fix it in plain words." | Carl pixel edition page 25: the exact recorded request; render 1 → render 2 |
| 52–56 s | "Publish. Share. Export." | Signed-out public reader recording, The Call of Cthulhu, pages 39–41 |
| 56–60 s | "Every story. Its own world." | Every drawn page from eight editions; no redundant count under the headline |
| 60–65 s | End card | Vector Panel Frame symbol, live Anybody wordmark, and `scenewright.ink` |

## Generation and project changes made for this cut

All in the test account, with the owner's authorization for paid generations.

- **Custom style proofs (`dcc1-2`):** 22 author directions submitted one at a time through the real *Bring a direction* composer, each recorded at 2× device scale. 21 finished; graffiti failed at the provider (`image_tool_failed`) and was not retried. Proofs that did not visibly match their direction (ukiyo-e ×2, first crayon, watercolor) are left out, not relabeled. 17 author-typed proofs appear in the flipbook beside the project's 11 existing proofs: 28 looks of one scene.
- **Loupe:** the Cthulhu reference proof is fine-grained pixel art that reads as painting at display size, so "Show it" adds a 2.5× crop of the real file, rendered with nearest-neighbor scaling.
- **Custom reference proof (`the-call-of-cthulhu`):** one upload + note, recorded end to end.
- **The Egg lettering:** page 21's balloons were placed by their speakers in the real editor and saved (lettering revision 6). The project was translated to Spanish and French (about 1 credit each) and returned to English. Every page now stores EN/ES/FR wording; the active language is English.
- **Backend fix:** project translation always failed with "inputs changed" when an account model selection differed from the project file. The job now rechecks with the admitted model selections (`lettering/translation.py`, covered by `test_account_selected_model_survives_the_job_snapshot_check`).

## Claims and their limits

- "Any style": every flipbook proof is a real proof of the same scene in one project. Proofs whose output did not match their direction are omitted, not relabeled.
- "As many as you want": the flipbook proofs were made for one project's scene; the Cthulhu proofs were made for that project, from its author's directions and Scenewright's suggestions. The Cthulhu set was accumulated over multiple directions and suggestions. The viewer-facing copy gives no style count or finite catalog claim.
- "One direction. A whole book": Cthulhu's selected style is the author-reference direction in proof 1 (`config.yaml`), and the displayed pages are from that finished edition. The film does not imply an existing edition can switch styles in place.
- "Same faces. Every page.": approved Cthulhu references guide drawing; the close-ups are from different pages of one edition. This is not a claim that every panel is identical.
- "Fix it in plain words.": one page redraw from the exact request. The first panel's "New achievement" text also changed, so the cut shows the jacket, not every letter.
- Lettering modes: integrated sound effects are drawn art; editable lettering is a separate layer. The Egg's first-draft placement needed manual adjustment, which is exactly what the editor shot shows.
- Translation: real project translation on the same artwork. Longer translations can need placement review.
- Export: PDF and CBZ are product capabilities; no export file is shown being created.

## Sound

`scripts/make-score-v2.py` synthesizes an original 120 BPM D-minor score plus sound design (stamps, page flicks, key clicks, whooshes, impacts) cued to the exact frames above. It uses no samples or external tracks. It is mastered to −14 LUFS integrated with peaks under −1 dBFS. Run it with numpy, scipy, soundfile and pyloudnorm available.

## Rebuild

1. `python3 scripts/prepare-v2.py`: copies current project art into `public/v2` (sources are read, never modified).
2. `python scripts/make-score-v2.py`: regenerates `public/v2/audio/score.wav`. Its flip cues are computed from the same schedule as `src/v2/scenes/Opening.tsx`.
3. Render the composition above. `ScenewrightShowcase` (the earlier 41-second cut) remains registered for comparison.

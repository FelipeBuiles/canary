# Comics craft for Adapt and Plan: adaptation choices, page plans and page turns

Research date: 2026-10-10. This note asks what comics practitioners, letterers, editors and visual-narrative research say makes a prose-to-comics adaptation good and a comic page plan readable and dramatic, and how the Adapt and Plan stages should apply that. It reviewed the Adapt prompts and schemas in `book_adaptation.py` (`build_narrative_treatment_prompt`, `build_adaptation_blueprint_prompt`, `build_book_adaptation_prompt`, `build_locked_lettering_prompt`, `_NARRATION_THOUGHT_GUIDANCE`, `validate_book_adaptation`), `models/adaptation.py`, `narrative_instructions.py`, `narrative_review.py` (`_prompt` and the computed signals), the Plan prompts, schemas and checks in `page_planning.py` (`_PanelCompositionDraft`, `_PageDraft`, `_PageMapEntry`, `_SEMANTIC_PAGE_CONTRACT`, `build_book_plan_prompt`, `_build_page_map_prompt`, `_detail_batch_prompt`, `validate_book_plan`, `_staging_failures`, `_speaker_acting_failures`, `_integrated_lettering_density_issues`), `models/page.py`, `gemini_tuning.py`, `combined_export.py`, [stage contracts](../reference/stage-contracts.md) and [CONTEXT.md](../../CONTEXT.md). It treats the July note, [Literary-to-comics adaptation](comics-medium-adaptation.md), as a reference only (section 7). The initial research was read-only; the implementation status below records subsequent changes. No provider was called for this research.

**Status (2026-10-10):** recommendations 1, 3, 8–10 and 14 are implemented; 2, 4, 11–12 and 16 are partial. Item 2 lacks the paraphrase signal; 4 has the grouped long-item note but no `caption_run`; 11 lacks the greater-than-nine-panel note and computed book-wide mean; 12 has edition-specific page-allocation budgets and page/panel density notes but no Plan per-item limit; 16 has silent-panel prompt guidance but no computed signal. Items 5–7, 13, 15 and 17 are not built. See [stage contracts](../reference/stage-contracts.md#comics-craft-guidance). Reader-visible effect is not yet measured on drawn pages.

The inspection findings below describe the pre-change pipeline. This status paragraph and the stage contracts describe the implementation.

**Resume and cost:** changed prompts invalidate matching saved generation requests. Review contract `narrative_v6` requires a fresh review pass where a current review is required; that pass can contain multiple window calls, protocol corrections and missing-context confirmations. It is not necessarily one paid call. Existing finished artifacts are not automatically regenerated.

Each finding carries an evidence label: **[Consensus]** means practitioners and sources broadly agree; **[Practitioner]** means a named professional's own statement; **[Empirical]** means a peer-reviewed study (or a preprint, flagged as such); **[Market]** means sales, award or company data. Disagreements are flagged where they appear. Project policy applies to every recommendation: padding, pacing, emphasis, panel variety and weak page turns are advisory and never block a run; exact lettering, source accounting and continuity are enforced.

## Executive summary

1. **Adapters cut description and keep the author's dialogue.** Fred Fordham used about a quarter of *To Kill a Mockingbird*, and about 90 percent of his text is Lee's own wording. P. Craig Russell takes "huge chunks of copy out" because the art shows rooms and scenes. Darwyn Cooke, Hope Larson and Paul Auster's *City of Glass* team kept the source dialogue nearly or entirely verbatim. Canary's base Adapt prompt allows free paraphrase outside protected language. Only the Gemini-only checklist says "prefer the source's own wording".
2. **Narration is a per-book decision, not a default.** Manu Larcenet kept only the dialogue of *The Road* and no captions. Cooke stripped present-day narration to essentials and used denser captions for flashbacks. Damian Duffy kept *Kindred*'s narrator voice through a narrator frame so he did not have to cut as much prose. Larson added "a few bits of internal monologue for clarity". Canary has a free-text `narrator_treatment`, but nothing measures whether the copy follows it.
3. **Canary pushes toward adding words and has nothing pushing back.** Adapt requires every causal link a still image cannot show to "appear in complete canonical lettering". The narrative review reports only missing context. Neither side checks for text that repeats the image. Todd Klein's first tip to writers is "write economically, and don't describe what the art is already showing". This imbalance is the most likely cause of text-heavy pages with stronger models.
4. **Word budgets are well established.** The commonly cited limits are 25 words per balloon at most, about 35 words per panel on a six-panel page, and about 210 words per page (Alan Moore relaying Mort Weisinger's DC rule). Dark Horse's script guide gives about 25 words per balloon and about 50 words per panel at most, and at most a comment, a response and a counter-response per panel. Canary gives these numbers only to Gemini models. The default Adapt and Plan model (`GATEWAY_SOL`) never sees them. Hybrid editions get no word-load signal at all.
5. **Panels per page have real reference values.** In 14,324 pages from 144 countries, the mean was 5.3 panels per page and the median 5. US comics fell from 6.2 panels per page in the 1940s to 4.8 in the 2010s. Asian comics hold near 5, and European comics run 7 to 9. Fewer panels always means larger panels (Cohn et al. 2026). Dark Horse recommends three or four panels for action pages.
6. **A page-turn reveal belongs at the top of a left-hand page.** Readers take in both pages of a spread before reading panels. A reveal on a right-hand page is seen at the same moment as its setup on the facing page. Canary's export starts each part on a right-hand page, so odd pages are rectos and even pages are versos. Plan's `page_turn_role`, `spread_role` and `weak_page_turn` never use this parity. The Gemini checklist even says to put a reveal "at the top of a page" without saying which side.
7. **Every reveal needs a visible setup, and dropped steps cost the reader effort.** When a bridging action is left out, readers spend longer on the next image and make more fixations to infer what happened (Magliano et al. 2016; Hutson et al. 2018). Narrative categories predict how readers segment a sequence better than McCloud-style panel transitions do (Cohn & Bender 2017). Canary's choice of Cohn's categories for `narrative_function` and `emphasis` is therefore the better-supported vocabulary, so no McCloud transition field is needed.
8. **Silence works only when the images carry it.** Cooke made *The Hunter*'s opening chapter wordless, and Larcenet spent up to three pages on one landscape description. Eye-tracking shows that panels without text are more likely to be skipped on a first read. Silent beats need large, clear action panels, not small transitional boxes.
9. **Orient the reader at every new place.** Jim Shooter's storytelling lectures define the long shot that "shows great scope" as the establishing shot. Cohn's research treats the Establisher as optional within a sequence. Canary authors per-panel setting, but has no signal when a location change opens on a close-up with no wide panel.
10. **Keep reading order and screen direction stable.** Dark Horse asks writers to list characters left to right in the order they speak. Klein says lettering reads left to right, then down. In film, cuts that break the 180-degree rule slow viewers' spatial processing (Huff & Schwan 2012). Practitioners say comics tolerate more because tails name the speaker, so this should stay advisory. Plan already asks for consistent screen direction in an exchange. Nothing checks that lettering reservations follow reading order.
11. **Much of Plan's craft guidance is already right.** The page count is advisory, one-panel pages are reserved for exceptional moments, silent sequences are allowed, shot sizes are varied, listeners face speakers, Peak and Release proportion is checked, and reveals are checked against the words on both sides of a turn. The gaps are specific: page parity, numeric budgets for every model, word-load signals for hybrid editions, establishing shots, balloon order and a check against redundant captions.
12. **The July note's information-preservation layer is implemented; the missing half is economy.** Its brief, ledger, treatment, narrative roles and review gates now exist. It has one mis-cited reference, gives no numbers, and does not mention page parity. Stronger models make the opposite failure more likely: over-explaining and text-heavy pages. Practitioners' main tool for that is cutting.

## 1. What adapters actually do

**Description becomes image; dialogue survives. [Consensus / Practitioner]**

- *To Kill a Mockingbird* (2018): Fred Fordham says he used about a quarter of Lee's novel, "bearing in mind that most of the visual description is translated into drawings". About 90 percent of the graphic novel's text is quoted directly from Lee. He found the novel easier to adapt because of its "rich dialogue" ([Poets & Writers, Nov/Dec 2018](https://www.pw.org/content/classic_meets_graphic_0)).
- *Coraline* and *The Graveyard Book*: P. Craig Russell says that with a novel "you're taking huge chunks of copy out", because prose describing a scene or room can be drawn instead. He also says "you have to take long dialogue scenes and shorten them" when a long novel meets a fixed page count. He calls choosing how many panels go on a page the creative core, and says "all of the acting and the pacing is done in the layout" ([Publishers Weekly, 2014](https://publishersweekly.com/pw/print/20140526/62407-it-takes-a-graveyard-to-raise-a-child-pw-talks-with-p-craig-russell.html)).
- *Parker: The Hunter* (2009): Darwyn Cooke told Westlake "your dialogue for me is perfect". He expected to write no more than "a couple of dozen sentences" of his own per book ([Comics Reporter, 2009](https://www.comicsreporter.com/index.php/brubaker_cooke_rough/)).
- *A Wrinkle in Time* (2012): Hope Larson says "very little of the dialogue changed" and she only "tweaked a few bits for space" ([The Beat, 2015](https://www.comicsbeat.com/interview-hope-larson-on-adapting-a-wrinkle-in-time)).
- *City of Glass* (1994): Auster's one condition was that "every word in the adaptation had to be written by him" ([Karasik interview, Comics Grinder, 2025](https://comicsgrinder.com/2025/04/06/paul-karasik-interview-on-comics-and-paul-auster/)).

Across these books, the cuts fall on description, summary and stage directions. The author's spoken lines are kept, though long exchanges are shortened. Canary's `PROTECTED_LANGUAGE_GUIDANCE` already says source descriptions are evidence of events, not instructions to reproduce them. It also says other prose "may be adapted into original dialogue". That second clause invites paraphrase where adapters keep the original line.

**Compression is uneven: summary shrinks, key moments grow. [Practitioner]**

- Ari Folman said a full adaptation of Anne Frank's diary "would take more than 3,500 pages". The book is 160 pages, and several letters to Kitty are kept in full ([AFP via Geo News, 2017](https://www.geo.tv/latest/158748-waltz-with-bashir-team-takes-on-anne-frank-story-in-graphic-novel)). He kept the most memorable philosophical entries intact. Other entries were turned into illustrations, "drastically shortened", or cut (Poets & Writers, above).
- Karasik: "What was 20-something pages in the book turned out to be a dozen in the comic." He also says "in comics, you don't need to say it if you can show it" (Comics Grinder, above).
- In the other direction, Larcenet says one of McCarthy's landscape descriptions "may sometimes take me three pages to render" ([The Beat, 2024](https://www.comicsbeat.com/interview-manu-larcenet-on-bringing-cormac-mccarthys-chilling-masterpiece-the-road-to-the-comics-page/)). Cooke turned the opening chapter of *The Hunter*, which is external description and people's reactions to Parker, into a wordless sequence. He wanted to "achieve the feeling of that chapter purely through the visuals" (Comics Reporter, above).
- Cooke also resisted enlarging a climax: "the trick here is to make less of it" (Comics Reporter, above).

There is no fixed compression ratio. Adapters decide where to compress and where to expand.

**Not every book should be compressed. [Practitioner]** Larson and her editor Margaret Ferguson tried cutting scenes from *A Wrinkle in Time* and found the story "is like a house of cards", resting on L'Engle's dialogue. They kept it nearly intact and accepted a long book. Larson did not want an adaptation that "relied heavily on caption boxes" to move the plot along ([Publishers Weekly, 2012](https://publishersweekly.com/pw/by-topic/industry-news/tip-sheet/article/54243-how-a-wrinkle-in-time-was-made-into-a-graphic-novel.html)). This supports Canary's rule that the target page range is advisory.

**Secondary characters and duplicate scenes are the usual cuts. [Practitioner]**

- Damian Duffy "removed and/or combined some secondary characters" in *Kindred*. He kept scenes "integral to the main characters' development" ([Beacon Broadside, 2017](https://beaconbroadside.com/2017/01/12/octavia-butlers-kindred-in-living-color-from-novel-to-graphic-novel)).
- When two scenes showed similar things, only one stayed ([Rumpus chat, 2017](https://therumpus.net/2017/02/22/the-rumpus-book-club-chat-with-damian-duffy-and-john-jennings)).
- His editor recognized that the "meta framing devices and time splicing made up the fat to be cut away" ([31 Days of Kindred, Day 3, 2016](https://damianduffy.net/?p=503)).
- He also notes that Butler links present events to past ones not yet described, which "does not easily lend itself to comics" ([Day 4, 2016](https://damianduffy.net/?p=514)).

Canary's ledger can already record `compressed_into` with a reason. The prompts do not tell the model that merging two scenes with the same function is a normal tool.

**Narration and interiority: four strategies that all worked. [Practitioner]**

| Book | Strategy | Owner's account |
| --- | --- | --- |
| *The Road* (Larcenet, 2024) | Dialogue only; no narration captions | "There was no point to rewrite and simply add images" (The Beat) |
| *Parker* (Cooke, 2009–13) | Present scenes: narration "stripped down to what I considered essential"; flashbacks: denser captions that signal a storyteller | Comics Reporter |
| *Kindred* (Duffy & Jennings, 2017) | A narrator frame (Dana dictating) so he "didn't have to cut as much prose" | 31 Days, Day 3 |
| *A Wrinkle in Time* (Larson, 2012) | Mostly dialogue; "a few bits of internal monologue for clarity" | The Beat |

Letterer Nate Piekos lists four caption types: Location & Time, Internal Monologue, Spoken and Editorial. He notes that thought balloons have "fallen out of fashion" in favor of internal-monologue captions ([Blambot, Comic Book Grammar & Tradition](https://blambot.com/pages/comic-book-grammar-tradition)). Canary's `_NARRATION_THOUGHT_GUIDANCE` already keeps narration as captions unless the source establishes in-the-moment inner words. That matches current practice.

**Market and award evidence for these adaptations. [Market]**

- Eisner Best Adaptation from Another Medium winners include Cooke's *Parker: The Hunter* (2010), *The Score* (2013) and *Slayground* (2014); Bá and Moon's *Two Brothers* (2016); *Kindred* (2018); and Junji Ito's *Frankenstein* (2019) ([Eisner past recipients, 2010s](https://www.comic-con.org/awards/eisner-awards/past-recipients/past-recipenties-2010s/)).
- Larson's *A Wrinkle in Time* won the 2013 Eisner for Best Publication for Teens (same source).
- *Kindred* reached #1 on the New York Times bestseller list ([The Nerds of Color, 2017](https://thenerdsofcolor.org/2017/01/19/john-jennings-damian-duffys-kindred-is-now-a-1-new-york-times-bestseller/)).
- The recognized adaptations span very lean (Larcenet, Cooke) to near-complete (Larson). What they share is verbatim dialogue, art that carries the description, and a deliberate narration strategy.

## 2. Words on the page: economy and budgets

**Economy is the letterer's first rule. [Practitioner / Consensus]** Todd Klein's tips for comics writers open with "write economically, and don't describe what the art is already showing" and "leave room for the art, this is not a novel". He adds that lettering reads left to right, then down, and should "form a natural flow for the eye across the page" ([Klein, 2017](https://kleinletters.com/Blog/lettering-tips-for-comics-writers/)). Cooke, Russell and Larcenet describe the same practice from the adapter's side (section 1).

**Quantitative budgets. [Practitioner]**

| Source | Per balloon | Per panel | Per page | Other |
| --- | --- | --- | --- | --- |
| Mort Weisinger's DC rule, relayed by Alan Moore | "25 words is the absolute maximum"; over 20–25 "looks too big" | 35 at six panels; about 23–24 at nine | "about 210 words per page maximum" | Moore counts script words "to make sure that I'm not going to overwhelm the pictures" ([Zarjaz #3 via downthetubes, 2013](https://downthetubes.net/?p=6793)) |
| Dark Horse script format guide | about 25 words | about 50 words, max | — | Action pages: three or four panels; at most "a comment, a response, and a counter-response" per panel; list characters "left to right" in speaking order ([Dark Horse guide](https://images.darkhorse.com/darkhorse08/company/submissions/DHScriptFormatGuides.pdf)) |
| Canary integrated editions (own OCR evidence) | — | — | flag above 110 words or 10 items | 24 drawn pages had no copy errors up to 87 words and 7 items (`_INTEGRATED_PAGE_WORDS`) |

The two practitioner sources agree on 25 words per balloon. They differ on words per panel (35 vs 50), and Weisinger's figure is tied to a six-panel page. **[Disagreement]** Brian Michael Bendis is widely cited as a successful exception who writes long dialogue. That is a matter of voice, not proof that walls of text are acceptable in general. I could not open the primary source for this (see the untraced claims).

**Empirical support: text draws and holds the eye. [Empirical]**

- Faces and text draw far more fixations than other regions in natural scenes ([Cerf, Frady & Koch 2009](https://resolver.caltech.edu/CaltechAUTHORS:20130816-103355264), cited in the style note).
- Yang (2024) reports that Laubrock et al. (2018) found text in comic panels attracts more attention than images, despite taking less area ([Yang, JEMR 2024](https://pmc.ncbi.nlm.nih.gov/articles/PMC11726626/)). I saw this only through Yang's citation.
- A related chapter by Vaughan, Murray, Kirtley and Tatler reports that more words, and a larger share of panel area given to words, lengthen dwell time on a panel (seen only through a search summary).
- Together: every extra word competes with the art for the same attention, and heavy text slows the page. This fits the practitioners' budgets, though no study I found sets a specific limit.

**Canary today.**

- **Gemini-only budgets.** `gemini_tuning.ADDENDA` carries "at most about 25 words" per lettering item and "under about 25 words" per panel. It also tells the map to avoid pages with more lettering "than about 4-6 panels can hold". These are appended only when `is_gemini_model(model)` is true. `Config.adapt_model` and `plan_model` default to `GATEWAY_SOL`, which receives none of them.
- **Integrated only.** `_integrated_lettering_density_issues` is the only word-load check, and it runs only for integrated editions.
- **No counterweight to adding context.** The Adapt prompts' "every causal link … must appear in complete canonical lettering" rule is right about comprehension. No prompt or review signal pushes the other way.

## 3. Sequence and page structure

**Narrative structure matters more than transition type. [Empirical]**

- *Segmentation:* readers drew sub-episode boundaries in panel sequences. Cohn's narrative categories predicted those boundaries better than linear semantic coherence relations between adjacent panels (changes in character, place or causation), though both had an effect ([Cohn & Bender, JEP:LMC 2017](https://research.tilburguniversity.edu/en/publications/drawing-the-line-between-constituent-structure-and-coherence-rela/)).
- *Bridging inference:* when a highly inferable bridging action is left out, viewers spend longer on the next image ([Magliano, Larson, Higgs & Loschky, Memory & Cognition 2016](https://doi.org/10.3758/s13421-015-0558-7)). The extra time goes into more fixations on regions that matter for the inference, not into longer fixations ([Hutson, Magliano & Loschky, Cognitive Science 2018](https://doi.org/10.1111/cogs.12699)).

The inference gap is a craft tool with a cost. For Canary, `narrative_function` and page `emphasis` (Establisher, Initial, Prolongation, Peak, Release) are the right vocabulary. Adding McCloud's six transition types as a schema field would add little.

**McCloud's transitions are descriptive and vary by tradition. [Practitioner; Empirical, weak]**

- McCloud's *Understanding Comics* found action-to-action transitions dominant in American comics and more aspect-to-aspect in manga. I know this only through secondary summaries.
- A 2023 preprint coded 2,228 manga panel pairs: action-to-action 33.2%, subject-to-subject 20.4%, non-sequitur 15.1%, moment-to-moment 12.6%, scene-to-scene 10.1%, aspect-to-aspect 8.3% ([Chen & Jhala, arXiv 2312.08720](https://arxiv.org/abs/2312.08720); not peer reviewed).
- Cohn's attentional framing data are similar. In Cohn (2011), as reported by Cohn, Taylor-Weiner & Grossman, nearly 60% of American panels showed several characters (Macros), with 35% showing one (Monos) and 5% close details (Micros). Manga had 47% Macros, 43% Monos and 10% Micros. Manga also uses more close-up environment-only panels ([Frontiers in Psychology 2012](https://doi.org/10.3389/fpsyg.2012.00349)).
- **Disagreement:** none of these is a quality rule. They describe styles. A Canary project in a manga-like style can reasonably use more single-figure and environment panels.

**Panels per page. [Empirical / Practitioner]**

- **TINTIN corpus** (1,030 comics, 14,324 pages, 144 countries): mean 5.32 panels per page, median 5, SD 2.4. Manga-style comics had fewer panels per page than cartoony ones. Across every style, region and decade, fewer panels meant larger panels; panel size alone explained 89.3% of the variance in panel count.
- **Cohn's Visual Language Research Corpus**, as summarized in the same paper: a mean of 6.4 panels per page (range 1–24). European comics averaged 7.94 and Flemish Belgian comics 10.4, against 5.3 for the US and 5.0 for Asia. US comics fell from 6.2 panels per page in the 1940s to 4.8 in the 2010s. European comics oscillated between 7 and 9, and Asian comics held near 5 from the 1980s on ([Cohn et al., Language Resources and Evaluation 2026](https://doi.org/10.1007/s10579-026-09925-9)).
- **Dark Horse:** "limit yourself to three or four panels per page" for action. More panels mean smaller panels, and "trying to cram too much information into small panels will result in a comic that's difficult to read" (Dark Horse guide, above).
- **Canary:** Gemini's checklist gives peaks and reveals 1–3 panels, establishing and transition pages 2–4, dialogue pages 4–6, and never the same panel count on more than three consecutive pages. Base prompts give no numbers; `density_intent` is "semantic intent, not panel-count or word-count caps". For a contemporary graphic novel, a book-level mean of about 4–6 panels per page with real variation is the empirical reference.
- **Splash pages:** I found no frequency data for full-page splashes.

**Shot progression and orientation. [Practitioner]**

- Jim Shooter defines a long shot as one that "shows great scope" and says it "is also known as an ESTABLISHING SHOT". Medium shots establish figures and body language, and close-ups carry emotion. He adds "these are tools not rules" and "be bulletproof clear. Then go for the gusto" ([Shooter, Storytelling lecture: artwork part 2, 2011](https://jimshooter.com/2011/04/storytelling-lecture-artwork-part-2.html/)).
- Wally Wood's "22 Panels That Always Work", compiled by Larry Hama from Wood's own reminder sheets, is a staple editors handed to new pencillers. It catalogs ways to vary talking-head panels: silhouette, foreground framing, depth, and over-the-shoulder ([downthetubes](https://downthetubes.net/creating-comics-wally-woods-panels-that-always-work/)).
- Cohn's Establisher is an optional category: a sequence can open on its Initial.
- Canary already asks Plan to vary shot size, keep unusual angles for emphasis, and author setting for every panel. It never asks for an orienting panel when the place changes.

**Screen direction and the 180-degree rule. [Empirical (film); Practitioner; disputed for comics]**

- In film, cuts that break the 180-degree rule slowed viewers' spatial judgments; congruent cuts let viewers use simple heuristics ([Huff & Schwan, Psychonomic Bulletin & Review 2012](https://doi.org/10.3758/s13423-012-0293-z)).
- I found no comics experiment on this. Practitioners argue comics tolerate more because tails name the speaker and a panel is not a moving cut. That claim comes from secondary creator commentary only.
- Dark Horse's rule to list characters left to right in speaking order is the editor-level version of the same idea.
- Canary already requires a reader's-screen `facing` for every visible character and asks that "an exchange keeps consistent screen direction". The evidence supports keeping this as guidance plus an advisory signal, not a hard rule.

**Reading order and balloon placement. [Practitioner / Empirical]**

- **Page navigation:** eye-tracking found that readers navigate pages mainly by panel borders. Text placement and content decide only when the layout is ambiguous ([Kirtley, Murray, Vaughan & Tatler, Applied Cognitive Psychology 2023](https://doi.org/10.1002/acp.4018)). As cited by Yang (2024), the same study found that panels without text are more likely to be skipped on a first read.
- **Balloon conventions:** Klein: left to right, then down. Piekos: tails point to the speaker's mouth, and an off-panel tail butts against the border (Blambot, above).
- **Canary's reservations:** `preferred_zone` and `footprint` give Plan enough vocabulary to state order. Nothing checks that the zones follow reading order, or that the first speaker is on the left.

## 4. Page turns and spreads

**The rule. [Practitioner / Consensus]** Katharine Woodman-Maynard places "suspenseful actions on the bottom right corner of a page spread" and "the reveal or payoff on the first panel of the following lefthand page". She calls this a general rule with exceptions. Her reason is that readers look at both pages of a spread before reading panels, so a reveal on the right-hand page catches the eye first and spoils the left-hand page. She plans spreads, not single pages, and marks the left or right side on each script page ([Woodman-Maynard, 2024](https://woodmanmaynard.substack.com/p/page-turns-crafting-suspense-in-comics)).

Other working creators make the same point ([SKTCHD, 2023](https://sktchd.com/longform/the-art-of-the-page-turn/); only the free introduction was readable):

- Kyle Starks calls the turn "the only real unknown" a creator has.
- Kelly Thompson calls it one of the few tools to "dictate how readers read".
- Kieron Gillen says the turn makes readers use their hands as well as their eyes, so the page needs propulsion to carry them across it.
- The same article notes that a double-page spread must always follow a page turn.

**Canary's page parity is fixed and known.**

- A single part's export starts at page 1. `combined_export.py` states that "each part starts on a right-hand page" and adds a blank page after a part that ends on a right-hand page.
- So for print and two-up reading, **odd pages are right-hand (recto) and even pages are left-hand (verso)**. A turn happens between each odd page and the next even page.
- The pair of an even page and the next odd page (2–3, 4–5, …) is one spread, seen at once.
- In single-page digital reading (a phone CBZ reader), every page boundary is a turn. A reveal at the top of an even page still works there, so the parity rule costs nothing digitally.

**What Plan does now.**

- **Prompts:** `_PageMapEntry` and `_PageDraft` let the model author `page_turn_role` and `spread_role` (`single`, `left`, `right`, `spread`) freely. No prompt says which pages are left or right.
- **Spread check:** the only validator, `page_spread_order`, rejects two consecutive pages declaring the same side. A plan can label page 1 `left`, which contradicts the export.
- **Weak page turn check:** `weak_page_turn` flags a reveal that opens a page when the previous page is not `setup` or `cliffhanger`. It does not notice that a reveal opening an odd page shares a spread with its setup.
- **Gemini checklist:** it says to put a reveal "at the top of a page, with its setup closing the previous page". On every odd page, that advice spoils the reveal.
- **Double-page spreads:** `spread` advertises a composition that Draw cannot make, because Draw generates one full page per request and has no cross-page composition. The model can therefore claim a spread that will never be drawn as one.
- **What is already good:** the map prompt's instruction to check "each proposed page-turn reveal against the exact lettering on both sides" is excellent. It catches words that give away a reveal before the image does, which is the same spoiler concern Woodman-Maynard describes.

## 5. Silence, decompression and pacing

**Silent sequences. [Practitioner / Empirical]** Larcenet wanted readers to "go through my drawings as if it were text". Cooke made a whole opening chapter wordless (section 1). The skipping finding (section 3) means a silent panel has to earn attention through size, a clear figure and a clear action. Canary's contract already allows silent sequences "when action, causality, and transitions remain self-explanatory". The narrative review already asks whether sustained silent runs are purposeful. Nothing asks Plan to give silent beats larger panels.

**Decompression. [Practitioner]** Cooke likes "a pacing shift-up on a longer form project", varying action, dialogue and dense narration. He also says he likes to work on a grid (Comics Reporter). Decompression in the sense of spending panels on one moment is what Larcenet and Cooke do with their wordless passages. Canary already allows a beat to repeat on adjacent panels or pages "when decompression reveals a distinct visual submoment". It flags beats spanning four or more pages and a third of the book (`concentration_*`). It also flags long runs of one-panel pages. These are proportionate advisory checks. What is missing is the decision about *where* to decompress, which belongs in Adapt's treatment.

**Peak and Release.** Plan's `poor_peak_release_proportion` and Adapt's `rushed_reaction_or_aftermath` already encode Cohn's arc. That is the right use of the research, and this note does not propose changes there.

## 6. How Canary's current prompts measure up

| Craft point | Current Canary state | Verdict |
| --- | --- | --- |
| Page count follows story, not target | Plan and Adapt say the range is advisory; never pad | Good |
| Description becomes image | `PROTECTED_LANGUAGE_GUIDANCE`: descriptions are evidence, not text to reproduce | Good |
| Keep source dialogue verbatim | Only Gemini: "Prefer the source's own wording"; base prompt permits "original dialogue" | **Missing for default models** |
| Do not caption what the art shows | No prompt; review checks only missing context | **Missing** |
| Words per balloon / panel / page | Gemini-only checklists; integrated-only page density issue | **Missing for default models and hybrid** |
| Narration strategy | Free-text `narrator_treatment`; strict caption/thought classification | Partly; strategy not measured |
| Where to decompress | `relative_emphasis` free text; no silent-sequence targets | Partly |
| Peak/Release, reveal follow-through | Implemented (advisory and faithful-mode checks) | Good |
| Panels per page | Gemini-only numbers; one-panel-run and dense-one-panel advisories | Partly |
| Page parity (recto/verso) | Not known to the planner; `spread_role` model-authored | **Missing / wrong** |
| Words that leak a reveal across a turn | Map prompt checks lettering on both sides | Good |
| Establishing shot at location change | Setting authored per panel; no orientation signal | **Missing** |
| Shot variety, unusual angles for emphasis | Prompt guidance; panel camera required | Good (no advisory signal) |
| Screen direction / listeners face speakers | Prompt guidance; acting-variety failures | Good |
| Balloon reading order, first speaker left | Zone vocabulary only | **Missing** |
| At most about three exchanges per panel | None | Missing |
| Silent panels sized to carry attention | None | Missing |

One documented tension: four consecutive identical facing and expression pairs (`repeated_character_acting`) and six or more appearances all in three-quarter view (`reference_angle_only`) are hard, Plan-repairable failures in `_staging_failures`. They look like panel-variety rules. [Stage contracts](../reference/stage-contracts.md) records them deliberately, as a guard against Draw copying the Cast reference pose. That is a rendering-fidelity reason, not a pacing preference, so this note leaves them alone. New variety checks proposed below are advisory.

## 7. The July adaptation note, revisited

[Literary-to-comics adaptation](comics-medium-adaptation.md) (2026-07-25) was written for weaker models and a pipeline that lost information.

**Where I agree, now implemented:**

- Fidelity judged at several levels.
- The adaptation brief and the per-source-unit ledger with dispositions and reasons.
- The carrier table, which gives each kind of source content its primary carrier.
- Cohn's arcs as a diagnostic, not a formula.
- Page turns as narrative units.
- Exact, untruncated lettering.

Canary has the brief (`AdaptationBrief`), the ledger (`AdaptationLedgerEntry`), the treatment (`NarrativeTreatment`), narrative roles on beats and pages, and staged review gates. Those recommendations need no repeat.

**Where I disagree or correct it:**

- Its `[^cohn-inference]` citation lists the authors as Cohn and Kutas. The paper at that link is Cohn & Wittenberg (2015), and it is about action stars. The claim that omitted Peaks are noticed more often is plausibly from the deletion experiments in [Cohn 2014](https://research.tilburguniversity.edu/en/publications/youre-a-good-structure-charlie-brown-the-distribution-of-narrativ/), but I could not read that result.
- I could not re-verify its Kirtley figures (41% of first fixations on text, text about 14% of the page area): the full text was blocked. They move to the untraced list.
- Its emphasis is almost entirely on not losing information: coverage, completeness, captions that are not cut off. That was the right fix for weak models. Practitioners' dominant move is cutting, and stronger models now add context generously. The missing half is economy: a counterweight in prompts and review against restating the image, plus explicit word budgets.

**What this note adds:**

- Quantitative word and panel budgets.
- Recto/verso parity.
- Establishing shots at location changes.
- Balloon reading order and speaker placement.
- Verbatim source dialogue as the default.
- A per-book narration strategy.
- Deliberately chosen silent or decompressed set pieces.

## Follow-up: panel shape and layout variety

**[Empirical]** Cohn's [Navigating Comics](https://doi.org/10.3389/fpsyg.2013.00186) and [Navigating Comics II](https://www.visuallanguagelab.com/P/NCHC_pagelayouts2.pdf) investigate reading paths, including empty layouts. Separation, overlap and vertical blockage can change navigation away from the familiar left-to-right, downward path. These results support preserving clear grouping and reading order; they do **not** establish that greater shape variety improves storytelling, or prescribe a layout for a genre. Cooke's preference for grids (section 6) is also a reason not to penalize intentional repetition.

**[Implementation judgment, not an empirical rule]** Plan now receives the approved Brief's tone. It chooses a coherent layout vocabulary in `rhythm_summary`, records motivated changes in page `rhythm_intent`, and describes proportions and row grouping in `layout_intent`. The global vocabulary and neighboring page intents reach parallel detail batches. Broad panels for a landscape or pause, tall panels for height, and larger panels for a decisive reaction are optional expressive choices, never quotas or genre formulas. Clear rectangles and gutters remain the default; unusual shapes need a specific narrative purpose and clear order. Steady grids remain valid. Draw receives the planned direction under existing style, identity and author-pin authority. A local replan preserves the accepted map's direction rather than importing a newly changed Brief tone.

No generated coordinates, mandatory variety score, new layout schema, automatic repair or additional paid call is added. Provider-free tests verify prompt/context delivery and preservation of Draw authority; only visual review can verify the rendered layout or its fit to tone.

**Evaluation:** compare Plan versions on identical locked Adapt first, then Adapt versions under the same Plan configuration. Record affected-page percentages and word-load distributions, not just grouped-note counts, alongside panel counts, reveal placement, fidelity, causality and narrator voice. Judge shape and layout choices on drawn pages in reading order, including two-up reading, before claiming quality gains.

## 8. Implications: recommended changes

Each item names what changes and the enforcement class. **Hard** means a blocking invariant; **advisory** means an `EditorialIssue` or review note that never blocks; **computed** means a deterministic, provider-free signal. Schema changes are forward-only and need the usual reruns under the no-back-compat policy. Nothing here relaxes exact lettering, source accounting or continuity.

### Adapt

1. **Promote the economy rules to every model** (prompt; advisory guidance). Move the substance of `ADDENDA["adapt.lettering"]` into `build_locked_lettering_prompt` and `build_book_adaptation_prompt` for all models:
   - one lettering item is one balloon or caption of at most about 25 words;
   - split longer speech into consecutive items at sentence boundaries;
   - cut speech tags and stage directions.

   Keep the Gemini checklist as a reinforcement, not the only carrier.
2. **Default to the author's dialogue** (prompt; advisory guidance; computed signal). Add a rule to `PROTECTED_LANGUAGE_GUIDANCE`, or Adapt's lettering prompt: when the source has a spoken line for the moment, use its words, shortening by selection rather than rewording. Reserve paraphrase for summarized speech and for fitting a balloon. Add a computed advisory `paraphrased_source_dialogue` in `validate_book_adaptation`. It fires when a dialogue item's cited source unit contains a quoted span but the item's text shares less than half its words with any quoted span. The protected-language tooling already extracts quoted spans (`_quoted_source_wording`).
3. **Add the missing counterweight: no captions that restate the image** (prompt; advisory review signal). In the Adapt prompts, next to the "every causal link must appear in lettering" sentence, add: captions carry voice, time and place, and interiority that is not visible; they never narrate visible action or appearance. In `narrative_review._prompt`, add `redundant_caption` as an advisory finding category with `consequence=editorial_preference`, never blocking.
4. **Computed word-load signals in Adapt** (computed; advisory). In `validate_book_adaptation`, add `long_lettering_item` (more than 25 words) and `caption_run`: three or more consecutive caption-only beats over a total of 75 words, a likely text wall. These give the author numbers before Plan, independent of model.
5. **Make narration strategy explicit** (Brief schema; advisory). Add a categorical `narration_strategy` to `AdaptationBrief`, inferred by Brief and editable by the author, next to the free-text `narrator_treatment`. Suggested values: `dialogue_only`, `sparse_captions`, `voiced_narrator`, `retrospective_frame`. These match the four strategies in section 1. Adapt prompts state the strategy's rule. A computed signal reports caption words as a share of all lettering against the strategy, for example over 15% under `sparse_captions`. Advisory only.
6. **Choose where to decompress in the treatment** (treatment schema or prompt; advisory). Ask `build_narrative_treatment_prompt` to name a few silent or near-silent set pieces per part, and the summary passages to compress hardest. The set pieces are moments where external description or reaction carries the scene, as in Cooke's opening chapter or Larcenet's landscapes. This can go in `relative_emphasis` with a stated format, or in a new `decompression` field. Plan's map prompt should give those beats extra pages and large silent panels.
7. **Allow scene merging explicitly for `medium_specific` and `transformative`** (prompt; ledger stays enforced). One sentence in the blueprint prompt: two source scenes with the same story function may be combined, recorded as `compressed_into` with a reason. This is Duffy's practice; the ledger already holds it. Merging characters remains blocked by Story Bible authority.

### Plan

8. **Compute page side; stop letting the model author it** (schema plus computed; deterministic metadata).
   - Derive `page_side = "right" if page_number % 2 else "left"` in one helper, kept in sync with the export layout: page 1 is a recto, and `combined_export.py` starts each part on the right.
   - Pass it in the page-map context and the detail `neighboring_page_map_context`.
   - Remove the model-authored `left` and `right` values of `spread_role` from `_PageMapEntry` and `_PageDraft`, and retire the `page_spread_order` check, which becomes redundant.
   - Remove `spread` until Draw can compose a double-page image. If a double-page composition is ever supported, it must start on an even page.
9. **Teach the turn rule in the page-map prompt** (prompt; advisory guidance). In `_build_page_map_prompt` and the Gemini `plan.map` checklist: `setup` and `cliffhanger` belong on right-hand (odd) pages, with the hook in the last panel. A turn `reveal` opens a left-hand (even) page in its first panel. Two facing pages are seen together, so a reveal on a right-hand page is seen with its setup. Fix the Gemini line "Put a reveal at the top of a page" to "the top of a left-hand (even) page".
10. **Extend `weak_page_turn` with parity** (computed; advisory). In `validate_book_plan`:
    - `reveal_on_recto`: a reveal beat opens an odd page other than page 1. The facing even page shows its setup at the same time. Suggest moving the reveal by one page.
    - `turn_setup_on_verso`: an even page is marked `setup` or `cliffhanger`, but no turn follows it.

    Both are advisory, and both name the page to shift.
11. **Promote panel guidance to every model and add a monotony signal** (prompt plus computed; advisory).
    - Move `_PANEL_RULES` into `build_book_plan_prompt` and `_detail_batch_prompt` for all models: peaks and reveals use 1–3 large panels, orientation and transition pages 2–4, dialogue pages 4–6, and action pages favor 3–4 (Dark Horse).
    - Add `uniform_panel_count`: the same panel count on four or more consecutive pages.
    - Add `crowded_page`: more than nine panels, which is rare outside European album traditions.
    - The book-wide mean panels per page goes in the plan summary as an informational number, reference about 5.
12. **Word-load signals for every edition** (computed; advisory). Generalize `_integrated_lettering_density_issues` into one function with per-edition thresholds:
    - **Hybrid:** an item over 25 words, a panel over 50 words, or a page over 210 words.
    - **Integrated:** keep 110 words or 10 items per page, and add the per-item limit.

    Feed the per-page word totals into the page-map context as computed numbers (lettering IDs to word counts), so the map allocates against them instead of counting by eye.
13. **Crowded exchanges** (computed; advisory). `crowded_exchange`: a panel whose on-screen dialogue alternates speakers more than three times (comment, response, counter-response). The repair is to split the panel or add a reaction panel.
14. **Orient at location changes** (prompt plus computed; advisory).
    - Prompt (`_SEMANTIC_PAGE_CONTRACT`): when the scene moves to a new place, one of its first two panels shows the place and who is where, with a wide, medium-wide or establishing shot. Withhold it only for deliberate disorientation.
    - Computed `unestablished_location_change`: the first two panels of a beat whose transitions include `dimension="place"` both have a `camera.shot` closer than `medium`. `PageContent` keeps `camera`; setting folds into `layout_intent`, so the check uses camera plus Adapt transitions.
15. **Balloon reading order and speaker placement** (computed plus prompt; advisory).
    - Computed `reservation_reading_order`: within one panel, the `preferred_zone`s of reservations, in locked lettering order, move backward. That means up a row, or right to left within a row.
    - Prompt: stage the first speaker on the reader's left, or high in the frame, so the balloons read in order. Keep balloons and tails off faces (Cerf 2009).
16. **Give silence room** (prompt; advisory). Add to the detail prompt: a silent panel carries its beat through a clear figure and action and gets a large share of the page. Do not turn a silent beat into a small transitional box. Optional computed signal: a page with three or more silent panels and five or more panels in total.
17. **Shot and direction signals** (computed; advisory, lower priority).
    - `uniform_shot_size`: every panel on a page with three or more panels has the same `camera.shot`.
    - `angle_overuse`: more than half the panels on a non-peak page use `dutch`, `worms_eye` or `overhead`.
    - `screen_direction_flip`: two characters in consecutive panels of the same scene swap left and right `facing` with no wide panel in between.

    The film evidence is indirect and practitioners disagree for comics, so these stay advisory and low in the review order.

### Ranked by expected reader-visible impact per cost

1. Items 1–3: economy rules for every model, verbatim source dialogue, and the anti-redundancy counterweight. These are prompt-only and directly target text-heavy pages.
2. Items 8–10: computed page side, the turn rule and the parity-aware `weak_page_turn`. These are small, deterministic changes, and visible in every print or two-up read.
3. Items 11–12: panel guidance for every model and word-load signals for hybrid editions. These are cheap and catch crammed pages before Draw spend.
4. Item 14: orientation at location changes. This is one prompt line plus one cheap check.
5. Items 15 and 13: balloon order and crowded exchanges. These are cheap computed checks that improve hybrid editor seeds and integrated readability.
6. Items 4–6: Adapt word signals, narration strategy and decompression targets. These involve a schema change, a Brief UI touch and a review signal. They are higher cost, with high value for voice.
7. Items 16, 7 and 17: silent-panel sizing, explicit scene merging, and shot and direction signals. These are lower or less certain impact.

Mocked tests do not establish reading quality. Judge items 1–3, 9 and 11 by drawing a small batch of real pages before and after on the same Adapt input and reading them, ideally printed two-up.

## Claims I could not trace to a primary source

- The page-level content of McCloud's *Understanding Comics* and *Making Comics*, Eisner's *Comics and Sequential Art*, Bendis's *Words for Pictures*, Janson's DC guides and Moore's *Writing for Comics*. This includes McCloud's transition percentages for American comics and the manga comparison, seen only in secondary summaries.
- Kirtley et al.'s figures that 41% of first fixations land on text, which occupies about 14% of the page (carried over from the July note; full text blocked). Their finding that textless panels are skipped more often, seen only through Yang (2024). Laubrock et al.'s text-attention result, seen only through Yang (2024). The Vaughan et al. word-count/dwell-time result, seen only in a search summary.
- The finding that omitted Peaks are noticed more often than other omissions. The July note's citation points to a different paper (Cohn & Wittenberg 2015, about action stars), and I could not read the deletion results of Cohn (2014).
- Duffy's tense split for *Kindred*: past-tense narration captions and present-tense thought balloons. This appeared only in a search summary, and none of the fetched pages confirmed it.
- Folman's claim that the edit uses "5 percent" of the diary's text (search summary only; the AFP piece confirms only the 3,500-page figure).
- John Ostrander's "three typed lines per balloon" rule (the page returned 403). Letterer Pat Brosseau's "no more than twenty balloons per page" (not fetched). Bendis as the long-dialogue exception (via Ostrander). Manga budgets of 25 words per panel and 60 per page (one blog only).
- Practitioner statements that the 180-degree rule matters less in comics: secondary creator commentary only. I found no comics experiment on screen direction.
- Any frequency data for splash pages, or for how often page-turn reveals occur in published graphic novels.
- Warren Ellis's own account of decompression, and Jim Shooter's interview criticism of it (not fetched).
- Sales figures for Fordham's *To Kill a Mockingbird* and Larson's *A Wrinkle in Time*, and *A Wrinkle in Time*'s final page count. None was checked.
- Gou Tanabe's account of adapting Lovecraft's first-person narration. I found no interview; only a 2017 Japan Media Arts Festival jury selection listing.

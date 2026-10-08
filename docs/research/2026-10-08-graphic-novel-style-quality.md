# Graphic novel style quality and the Style proof portfolio

Research date: 2026-10-08. This note asks what established practice and evidence say makes a comic style good and likable to readers, and how the Style stage's six-proof portfolio should apply that. It assumes the known causes of dull, warm proofs: Extract `style_notes` prescribes color, color is not a curated diversity axis, the palette field does not reach the image prompt, and GPT Image adds a warm cast. Fixes for those are already planned. This note does not re-derive them. It reviewed `_SKETCH_SYSTEM_PROMPT`, `_portfolio_distance`, `_select_role_portfolio` and `STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT` in `stages/s2_style.py`, `STYLE_PROOF_ART_CONSTRAINTS`, `style_contract.py` and `style_briefing.py`. No code was changed and no provider was called.

Each finding carries an evidence label: **[Consensus]** means practitioners and sources broadly agree; **[Practitioner]** means a named professional's own statement; **[Empirical]** means a peer-reviewed study; **[Market]** means sales, award or company data. Disagreements are flagged where they appear.

## Executive summary

1. **Readers judge clarity first and color second.** Image Comics asks pitches for five inked and lettered pages and states that color is optional ([Image submissions](https://imagecomics.com/submissions)). Colorists describe their job as leading the eye and keeping the story easy to follow. A proof that fails on figure–ground separation, facial clarity or panel flow cannot be rescued by its palette.
2. **Plan values before hues.** Professional colorists use value and hue variation to lead the eye and separate planes. Darker or heavier color can bury line art. Each proof should show a clear light–dark hierarchy, with the focal face at the strongest contrast.
3. **Limit the palette, but do not drain it.** Acclaimed colorists use restricted, motivated palettes and change them from scene to scene. They do not use one dull, uniform cast. Restriction is about color relationships, not low saturation. Empirically, people prefer saturated colors, and **browns, dark yellows and olives rank among the least liked**. That is close to the sepia/warm cast seen across Canary's proofs ([Palmer & Schloss 2010](https://pmc.ncbi.nlm.nih.gov/articles/PMC2889342)).
4. **More color is not automatically better.** A large crowd-sourced study found no direct linear relationship between image colorfulness and aesthetic rating. The relationship depends on the kind of image ([Amati, Mitra & Weyrich 2014](https://reality.cs.ucl.ac.uk/projects/image-colourfulness/image-colourfulness.html)). The portfolio should vary color *strategy*, such as full, limited, spot or high-key color, rather than simply raising saturation.
5. **Color should change across a book.** Pixar color scripts and colorists such as Dave Stewart break scenes into separate color schemes. Stewart says a single look held for a long scene becomes dull. A proof style needs a palette system that can shift with mood, not one fixed tint.
6. **Simplified faces communicate emotion faster and cost less to repeat.** Iconic faces improve emotion recognition at brief viewing times ([Kendall et al. 2016](https://doi.org/10.1186/s41235-016-0021-8)). Iconic and realistic drawings produced the same empathy when the story was the same ([Lee, Choi & Jeong 2017](https://peerj.com/articles/3988)). Faces and text attract gaze regardless of task ([Cerf, Frady & Koch 2009](https://resolver.caltech.edu/CaltechAUTHORS:20130816-103355264)).
7. **Market leaders use comic-native styles.** Kids' bestsellers use clean line art with bright, flat color, including *Dog Man* and the color *Bone* and *Baby-Sitters Club* reissues. Adult bookstore charts are led by black-and-white manga and full-color webtoon collections. Fine-art media and novelty processes are absent from those charts. Canary's sketch medium list contains only fine-art media and no comic-native production styles.
8. **Restricted palettes win critical prizes when the story motivates them.** Examples include *Asterios Polyp*, *This One Summer*, *The Sculptor*, *The Arrival* and *Radioactive*. Each creator tied the hue or process to the subject or to practical production limits, and kept a full light-to-dark value range.
9. **Novelty media can carry books, but only as small-press art objects.** Examples are cut-paper, embroidery and woodcut novels. No book-length cyanotype, stained-glass or diorama comic was found. **Recommendation: gate cyanotype and similar novelty processes; do not veto or keep them freely.** Allow them only as a wildcard with a stated story connection, or when the author asks. Allow at most one single-hue proof, and render it as positive line art on a light ground.
10. **Choose a charged moment, not a quiet one, while still avoiding the climax.** Lessing's pregnant moment calls for the instant that suggests what came before and what follows ([Laocoön, 1766](https://www.gutenberg.org/ebooks/73078)). The current brief asks for a "quiet, characteristic micro-beat", and `style_sample_selection` uses the first eligible scene. Both work against the one page that has to sell the style.
11. **Production feasibility counts as quality.** Creators choose monochrome or spot color because full color and painting are slow and hard to control: McCloud, Tan and Ross's roughly ten painted pages a month show this. For Canary, the comparable cost is drift between pages. Heavily textured, accident-driven media are harder to keep consistent across 100+ generated pages than line-led styles.

## 1. Color in sequential art

**Value carries readability; hue carries mood. [Consensus / Practitioner]** Dave Stewart, a multiple Eisner coloring winner, plans how color will "lead the eye with variation in value and hue". He wants color to support line art rather than overpower it ([Manchess interview, 2010](https://reactormag.com/an-interview-with-colorist-dave-stewart/)). Jordie Bellaire, who won Best Coloring in 2023, 2024, 2025 and 2026, says she tries to separate every plane on the page. She describes a colorist's role as making sure the reader follows the story ([A.V. Club, 2016](https://avclub.com/comics-colorist-jordie-bellaire-on-the-art-of-coloring-1798250467)). Cliff Chiang says that on *Paper Girls*, darker colors could overwhelm the line art. The team aimed for "ultra-readable and approachable" color ([Image Comics](https://imagecomics.com/features/cliff-chiang-the-look-of-paper-girls-gallery)). The common rule is to choose a value hierarchy first, then pick hues within it. I could not access the color chapters of Abel & Madden's *Mastering Comics* or Gurney's *Color and Light*, so this rule rests on the colorists' own statements.

**Limited palettes are a tool for meaning, not a flavor. [Practitioner]** Bellaire's *Pretty Deadly* uses a fixed color code: green for bad, blue for dead. On *Manhattan Projects* she used deliberately pure reds and blues, not murky ones (A.V. Club, above). James Gurney's gamut-masking method selects a bounded color range for a whole painting. What lies outside that range is what "you want to leave out" ([Gurney Journey, Part 2, 2011](https://gurneyjourney.blogspot.com/2011/09/part-2-gamut-masking-method.html)). A limited palette is therefore a chosen set of color relationships that can include saturated accents. It does not mean low chroma everywhere.

**Use local and scene color, and let it change. [Practitioner]** Stewart says he likes to break scenes into different color schemes. He sometimes adjusts saturation or hue across a whole book to fit its theme. He also changes the light within a long scene, for example to sunrise or sunset, so it does not go flat. On *Joe the Barbarian* he gave two worlds separate color treatments as an instant cue (Manchess, above). Pixar has made a color script for every film since *Toy Story*. In it, color intensity rises with emotion and becomes muted when the story turns somber ([MoMA audio guide, Pixar: 20 Years of Animation](https://www.moma.org/audio/playlist/192/2581)). For Canary, a style should define a palette *system*: base local colors plus room for mood shifts per scene. It should not be one fixed tint applied to every page.

**Flat and rendered color both work; the market and colorists lean flat. [Practitioner / Market]** Chiang's *Paper Girls* team deliberately stepped back from a saturated, rendered look to do more with less (Image Comics, above). Gregory Manchess credits Stewart with creating depth from flat color (Manchess, above). Laura Allred won the 2012 and 2021 Best Coloring Eisners for flat Pop color ([Eisner past recipients, 2010s](https://www.comic-con.org/awards/eisner-awards/past-recipients/past-recipenties-2010s/), [2020s](https://www.comic-con.org/awards/eisner-awards/past-recipients/past-recipenties-2020s/)). Kids' bestsellers also use clean, flat color (section 3). Painted color remains a valid prestige choice. Section 2 covers the costs it brings.

**Saturation and preference: the evidence is real but bounded. [Empirical; partly disputed]**

- Palmer & Schloss had observers rate 32 chromatic colors. Saturated colors were preferred over light, muted and dark colors. Dark yellow (olive) had the deepest dislike, with dark orange (brown) close behind ([PNAS 2010](https://pmc.ncbi.nlm.nih.gov/articles/PMC2889342)). Their explanation is that people like colors associated with things they like, such as clear sky, and dislike colors associated with things like rot. This is independent evidence that a uniform warm, sepia or olive cast is a poor default.
- Amati, Mitra & Weyrich found **no direct linear link** between colorfulness and aesthetic rating across a large crowd-sourced set. Correlations appeared only within some image categories, such as landscape, abstract and macro ([ACM CAe 2014](https://reality.cs.ucl.ac.uk/projects/image-colourfulness/image-colourfulness.html)). They also found Hasler & Süsstrunk's perceptual colorfulness metric closest to user judgments ([Hasler & Süsstrunk 2003](https://infoscience.epfl.ch/record/33994)). This metric is suitable for an offline proof-colorfulness check.
- Albers, Gegenfurtner & Nascimento found that a painting's color composition contributes to preference independently of its spatial layout. Observers preferred the original hue arrangement over hue-rotated versions with the same lightness and saturation ([Vision Research 2020](https://doi.org/10.1016/j.visres.2020.08.005)). In other words, coherent color relationships matter, not only how much color there is.
- **Disagreement:** In comics specifically, I found no controlled study comparing color and black-and-white for reader preference or comprehension. The commercial evidence cuts both ways. Black-and-white manga leads the adult charts, while kids' publishers colorize black-and-white books to widen their audience (section 3).

**Visual complexity. [Empirical; disputed]** Berlyne's inverted U, where preference peaks at middling complexity, is often reported. A 2016 study found that the average curve can come from two groups: most participants preferred simpler images, while a minority preferred complex ones ([Güçlütürk, Jacobs & van Lier 2016](https://www.frontiersin.org/articles/10.3389/fnhum.2016.00112/full)). The practical takeaway is to give the portfolio a range of detail densities rather than six highly detailed proofs.

## 2. Line, rendering and legibility across a book

**Simplification increases clarity. [Practitioner + Empirical]** McCloud's *Understanding Comics* (1993) argues that cartooning amplifies meaning by simplifying it: the artist focuses on specific details rather than removing detail. I did not open the book. The wording here comes from secondary summaries ([course handout](https://cowell.ucsc.edu/academics/courses/Understanding%20comics.pdf)). Kendall et al. tested this idea. As faces moved from photographic toward iconic, emotion was identified more accurately at short exposures, and lower featural complexity and higher contrast helped ([Cognitive Research 2016](https://doi.org/10.1186/s41235-016-0021-8)). **Disagreement:** McCloud's claim that simple faces increase reader identification is not well supported. A 50-participant eye-tracking and EEG study found no empathy difference between iconic and realistic drawings of the same story. The authors concluded that plot outweighs drawing style ([Lee, Choi & Jeong, PeerJ 2017](https://peerj.com/articles/3988)). Simplified styles are a clarity and cost benefit, not a guaranteed empathy benefit.

**Faces and text are where the eye goes. [Empirical]** In free viewing of natural scenes, faces drew 16.6 times and text 11.1 times more fixations than comparable regions. Observers also struggled to avoid them when told to ([Cerf, Frady & Koch, Journal of Vision 2009](https://resolver.caltech.edu/CaltechAUTHORS:20130816-103355264)). For a proof page, the focal face is the first thing a reader judges. Its legibility, meaning size in frame, value contrast and a clear expression, deserves priority over background texture.

**Silhouette and line-weight hierarchy. [Consensus; primary text not accessed]** Inking manuals teach varied line weight to create depth and separation. Klaus Janson's *DC Comics Guide to Inking Comics* covers line weight and light/dark design ([catalog](https://www.goodreads.com/book/show/199173)). Readable silhouettes are a long-standing animation and comics principle. I could not access a primary passage for either point, so treat them as consensus craft knowledge without a pinned citation. `STYLE_VALIDATION_ACTION` already asks for a "readable silhouette". The default proof action does not.

**Detail density at reading size. [Market / Practitioner]** WEBTOON reports about 157 million monthly users on a vertical format built for phones ([WEBTOON 10-K FY2025](https://www.sec.gov/Archives/edgar/data/1997859/000199785926000028/wbtn-20251231.htm)). Kids' graphic novels are printed at small trim sizes; Graphix's color *Bone* launched at 6×9 inches ([Graphix launch announcement](https://www.writerswrite.com/scholastic-launches-new-graphic-novel-7132004288)). Fine hatching, small faces in wide shots and low-contrast texture disappear at those sizes. This is an inference from format; I found no measurement study on it.

**Repeatability and production cost. [Practitioner]** Creators often choose a restricted style because full color and painting are slow and hard to control.

- Scott McCloud chose black, white and blue for *The Sculptor* "partially out of necessity". He found full color hard, expensive and labor-intensive, and used the second color to clarify form ([Village Voice, 2015](https://www.villagevoice.com/?p=389604); [Bookreporter, 2015](https://www.bookreporter.com/authors/scott-mccloud/news/interview-020315)).
- Shaun Tan considered oil paint for *The Arrival* but said it "would have taken forever". He chose monochrome for production reasons ([Publishers Weekly, 2007](https://www.publishersweekly.com/article/406854-Children_s_Bookshelf_Talks_with_Shaun_Tan.php)).
- Alex Ross paints about ten interior pages a month ([Hollywood Reporter](https://www.hollywoodreporter.com/news/general-news/alex-ross-graphic-novel-marvel-dimensions-1236496183/)).
- Painted, mixed-media books can sell while drawing readability complaints. Paul Gravett notes that *Arkham Asylum* earned Dave McKean a wide following ([Gravett](https://paulgravett.com/articles/article/dave_mckean)), while reviewers say its images often get in the way of the story ([The Slings & Arrows Graphic Novel Guide](https://theslingsandarrows.com/?p=10351)).

Canary does not pay per hour. Its comparable cost is **consistency drift**: a style defined by process accidents is harder to reproduce identically across many pages and Cast sheets than one defined by line, shape and flat color. Examples of such accidents are cyanotype exposure, paper texture, wax resist, dry-brush scratch and diorama lighting. This is an inference for generated art, not a measured result.

**Regional visual languages. [Empirical, not read in full]** Neil Cohn's *The Patterns of Comics* (Bloomsbury, 2023) annotates more than 36,000 panels from over 350 American, European and Asian comics. It reports regional differences in symbols, layout and storytelling, and how comics changed over 80 years ([publisher announcement](https://dev.linguistlist.org/issues/35/2358/)). One secondary review says American comics have moved toward manga framing. I could not confirm that in a primary text.

## 3. Reader appeal and market evidence

**Bestsellers. [Market]**

- **Kids:** In the November 2023 Circana BookScan Top 20 kids' graphic novels, Dav Pilkey had eight entries, seven of them *Dog Man*. The rest of the list included *Baby-Sitters Club*, *Five Nights at Freddy's*, *Investigators* and *Cat Kid* ([ICv2](https://icv2.com/articles/markets/view/55750/november-2023-circana-bookscan-top-20-kids-graphic-novels)). These books share clean line art, iconic characters and bright, flat or lightly shaded full color.
- **Colorizing black-and-white books for children:** Scholastic's full-color *Bone*, colored from Jeff Smith's 1991 black-and-white comic, reached 2.5 million volumes in print by 2009 ([Publishers Weekly, 2009](https://www.publishersweekly.com/pw/by-topic/booknews/comics/article/10369-jeff-smith-s-bone-saga-ends-again.html)). Graphix called its full-color reissues of Telgemeier's black-and-white *Baby-Sitters Club* books "successful" and expanded the series ([Publishers Weekly, 2016](https://www.publishersweekly.com/pw/by-topic/childrens/childrens-book-news/article/70431-graphix-to-expand-baby-sitters-club-graphic-novel-series.html)). For young readers, publishers treat full color as a reach multiplier.
- **Adult book channel:** The August 2025 Top 20 adult chart was 17 manga or webtoon titles plus three superhero editions. *Solo Leveling*, a full-color webtoon collection, ranked first ([ICv2](https://icv2.com/articles/markets/view/60492/august-2025-circana-bookscan-top-20-adult-graphic-novels)). In the full-year 2025 Author chart, 13 of the 14 *Solo Leveling* volumes in print appeared ([ICv2](https://icv2.com/print/article/61464)). The full ranked Kids and Adult year-end lists are behind ICv2 Pro and were not read. Black-and-white manga with screentone sells strongly to adults. Value design, character design and serial habit carry those books, not hue.
- **Market size:** Comics and graphic novel sales in the US and Canada were about $1.94 billion in 2024. Periodical comics were about $460 million of that, so graphic novels were roughly three quarters ([ICv2, July 2025](https://icv2.com/articles/markets/view/60012/)).

**Critical acclaim. [Market — awards]** Recent Eisner Best Graphic Album—New winners split between restricted and full palettes ([2010s](https://www.comic-con.org/awards/eisner-awards/past-recipients/past-recipenties-2010s/), [2020s](https://www.comic-con.org/awards/eisner-awards/past-recipients/past-recipenties-2020s/), [2026](https://www.comic-con.org/awards/eisner-awards/)):

- **Restricted palettes:** *Asterios Polyp* (2010), *This One Summer* (2015), *Monsters* (2022, black and white).
- **Full color:** *Pulp* (2021), *The Night Eaters* (2023), *Lunar New Year Love Story* (2025).
- **Distinctive non-standard media:** *My Favorite Thing Is Monsters* (2018, ballpoint pen on notebook paper; also Best Coloring).

Kids' and Teens' winners are mostly full color, for example *Guts*, *Mexikid*, *Plain Jane and the Mermaid* and *The Cartoonists Club*. Literary and adult prestige tolerates and rewards restriction. Children's and general audiences reward clean full color.

**What this means for Canary's audience. [Inference]** Canary adapts novels for authors who will publish to unknown audiences. Six proofs should therefore cover the market's proven styles: clean line with flat or soft full color; a manga/screentone or ink-and-tone black-and-white option where it fits; and a painterly or limited-palette prestige option. Novelty options belong at the edge of the set.

## 4. Novelty and single-hue media: precedents and the cyanotype question

**Single-hue books that worked, and why. [Market — awards / Practitioner]**

| Book | Treatment | Recognition | Why it worked (owner's account where available) |
| --- | --- | --- | --- |
| *This One Summer* (J. & M. Tamaki, 2014) | One blue ink for line and wash on white paper | First graphic novel with a Caldecott Honor; Printz Honor; 2015 Eisner ([CBC Books](https://cbcbooks.org/2015/02/05/this-one-summer-becomes-the-first-graphic-novel-to-win-a-caldecott-honor/)) | Brush line keeps the full range from paper white to deep blue; the hue fits a lakeside summer mood. I did not find the artist's own explanation. |
| *The Sculptor* (McCloud, 2015) | Black line plus a grayish blue spot color | Major-publisher release (First Second) | Chosen partly from necessity; the second color clarifies form ([Village Voice](https://www.villagevoice.com/?p=389604)). |
| *The Arrival* (Tan, 2006) | Graphite in sepia tones | Took five years to make (awards not checked here) | Production limits, plus the sepia of old photographs fits an immigration story ([PW](https://www.publishersweekly.com/article/406854-Children_s_Bookshelf_Talks_with_Shaun_Tan.php)). |
| *Radioactive* (Redniss, 2010) | Cyanotype for many images | First visual book named a National Book Award nonfiction finalist ([Wikipedia summary of NBF citation](https://en.wikipedia.org/wiki/Radioactive_(Redniss_book))) | The process is the subject: cyanotype is tied to the discovery of X-rays and radioactivity. It is an illustrated nonfiction book, not a paneled comic. |
| *Gods' Man* (Ward, 1929); *Flood!* (Drooker, 1992) | Woodcut / scratchboard wordless novels | *Gods' Man* sold 20,000+ copies; Library of America edition ([PW](https://www.publishersweekly.com/pw/by-topic/booknews/comics/article/45192-loa-publishes-lynd-ward-s-wordless-graphic-novels.html)); *Flood!* won an American Book Award ([Dark Horse](https://www.darkhorse.com/pressrelease/new-yorker-artist-eric-drooker-unleashes-flood-a-novel-in-pictures-with-dark-horse-comics)) | Strong black-and-white value design. Literary and art-book audience. |

The pattern is consistent. These books (a) have a reason in the story or in production for the hue or process; (b) keep a **positive, full value range**, meaning dark line or tone on a light ground with deep accents; and (c) are made by artists who control the process.

**Novelty media with book-length precedents.** The examples are small-press art objects:

- Eroyn Franklin's cut-paper *Another Glorious Day at the Nothing Factory* (Xeric grant, edition of 1,000) ([Copacetic Comics](https://copaceticcomics.com/creators/eroyn-franklin)).
- Joe Boruchow's 100-cutout *Stuffed Animals* (four years' work) ([Stencil Archive](https://www.stencilarchive.org/content/joe-boruchow-releases-stuffed-animals-cutout-graphic-novel)).
- Gareth Brookes's embroidered *Threadbare* (56 pages) ([Goodreads listing](https://www.goodreads.com/book/show/50398588-threadbare)).

I found **no book-length comic** in cyanotype, stained glass, origami or diorama. This is absence of evidence from a limited search, not proof that none exist.

**The case against cyanotype as a default proof.** These points are inferences from the evidence above:

- A cyanotype *as a process* tends to produce a dark Prussian-blue field with pale subjects, like a photogram or a blueprint. That reverses the positive value structure the successful blue books use.
- It compresses the midtones that model faces. Photographers report a limited tonal range for traditional cyanotype; this is forum evidence only, not a measured source ([Photrio thread](https://www.photrio.com/forum/threads/a-question-about-cyanotype-process.110945/)).
- It removes hue as a carrier for scene color, which Stewart and Pixar use to separate scenes and moods. One blue across a whole book loses that tool.
- It worsens the low-colorfulness problem already seen across Canary's proofs.
- The owner and two test users dislike it. Three reactions are only a signal, but this note found no evidence against them.

**Recommendation: gate, do not veto, do not keep as-is.**

- **Why not veto:** Single-blue books win major prizes, and *Radioactive* shows cyanotype can serve the right subject. Authors may explicitly ask for a blueprint or sun-print look. A keyword denylist would be brittle: cyanotype, blueprint, sun print, Prussian blue and photogram all mean similar things. It would also contradict the prompt's rule that explicit author constraints take precedence.
- **Why not keep:** No sequential precedent exists. The process conflicts with face legibility and scene-color variation, and it keeps reappearing because the sketch prompt lists it and the curation rewards rarity (section 6).
- **Gate conditions:**
  - Allowed only when the author's direction asks for it (`medium_restriction`), **or** as the `wildcard` role with a `story_fit` that names a concrete link to the story, such as light, photography, the sea, cold, science, plans or memory.
  - At most one single-hue/monochrome proof per portfolio, and never in a `story_fit_*` role unless the author asked.
  - The template must specify **positive rendering**: dark line and tone on a light ground with a full value range, not a white-on-dark negative field.
- **Apply the same gate to every novelty process.** Examples are stained glass, origami, diorama, wax, clay, papier-mâché, batik and mosaic. Add other process-driven mediums only where this concern also applies.

## 5. What makes one proof page persuasive

**Choice of moment. [Practitioner — classical text + Empirical]**

- **Avoid the climax, as the current brief already does.** Lessing argues that a single image should not show the peak of an action, because nothing is left to imagine. A painter should choose "the most pregnant" moment: the one that most suggests what came before and what follows ([Laocoön, ch. 3 and 16](https://www.gutenberg.org/ebooks/73078)).
- **But a three-panel page needs a small turn.** Cohn's narrative grammar treats the *Peak* as the one essential category. *Establisher* and *Initial* panels set it up ([Cohn 2013, Cognitive Science](https://doi.org/10.1111/cogs.12016); I saw the paper's summary, not the full text).
- McCloud lists choice of moment first among his five storytelling choices (*Making Comics*, 2006; table of contents only).
- The current setup works against this. The brief asks for a "quiet, characteristic micro-beat". `style_sample_selection` takes the first scene with one to four known characters, which is often expository. The result is a page of people standing in a place. It fails the "is this a real comic?" test however good the rendering is.

**Focal face and expression. [Empirical]** Gaze goes to faces (Cerf 2009). Simplified faces read emotion faster (Kendall 2016). The current composition already ends on an "expressive detail". It should be a face with a specific, readable emotion caused by the moment, not a hand or prop detail.

**Lighting and depth. [Practitioner]** Stewart wants color to give the page depth rather than leave it flat, and plans value to lead the eye. Bellaire separates foreground, middle and background planes. The brief already names a physical light source. It should also ask for figure–ground value separation and at least two depth planes in the establishing panel. Value structure should stay with the candidate style (section 6).

**Finish and the first impression. [Market / Practitioner]** Editors judge storytelling first. Image wants inked and lettered sequential pages and a cover mock-up that shows "whether or not you understand the market" (Image submissions). For Canary this supports the existing design: borders, gutters and lettering on every proof. It also argues against proofs that read as illustrations or art-medium demos rather than comic pages.

**Not found:** I found no empirical study of what makes a single sample page or cover sell a graphic novel. The guidance above combines editor requirements with attention and perception studies.

## 6. Implications for Canary's style proofs

**Status (2026-10-08):** items 1, 2 (the single-hue cap; the `muted`-accent refinement is not implemented), 3, 4, 5, 6, 7, 8 (stopwords and a categorical `medium_family` term), 9, 10, 11, 12, 13, 14, 15 and 16 are implemented in `s2_style.py`, `style_briefing.py` and `style_contract.py`. Item 17 (offline colorfulness scoring and pick analytics) is not. The rest of this section is the original proposal text.

These are proposals. Schema changes are forward-only and need a `SUGGESTION_SCHEMA_VERSION` / `STYLE_BRIEF_VERSION` bump, per the no-back-compat policy.

**Overlap with in-progress work.** On the research date, an uncommitted change in this checkout already adds a categorical `ColorStrategy` to `StyleSketch`, with six values: monochrome, spot_color, muted, naturalistic, saturated and high_key. The same change adds:

- a `color_restriction` field;
- a 0.5 color term in `_portfolio_distance`;
- a `require_color_diversity` rule in `_select_role_portfolio`: at most two low-chroma options and at least two full-color options;
- a prompt rule that a bleak story is not a request for sepia.

This research supports that direction, so items 2, 7 and 9 below describe it and build on it rather than proposing it from scratch. The findings add four things the change does not yet cover:

- at most one single-hue option;
- positive rendering for single-hue styles;
- gating of novelty media;
- comic-native production styles in the medium list.

### `_SKETCH_SYSTEM_PROMPT` (brainstorm and curate)

1. **Add comic-native production styles to MEDIUM, and split the list.** The current list contains only fine-art media and processes. It is missing the styles that dominate sales and awards: ink line with flat color; *ligne claire*; brush ink with digital painting; ink with watercolor or gouache washes; manga ink with screentone; pencil with gray tone; two-color/spot-color or risograph print; animation-style cel shading. Put these in a "core sequential" list. Move cyanotype, stained glass, origami, diorama, wax, clay, papier-mâché, batik and mosaic to a "novelty process" list governed by the gate in section 4.
2. **Keep the color strategy quota, and tighten it** (partly in progress). The in-progress `ColorStrategy` covers the main strategies. The evidence suggests three refinements. First, cap *single-hue* options (monochrome or one ink) at one, separately from the two-option low-chroma cap. Second, count `muted` as full-color only when the palette names a saturated accent. Third, treat sepia or aged-paper tones as acceptable only with a story reason, as in *The Arrival*. Brown, olive and dark yellow are the least-liked hues (Palmer & Schloss).
3. **Describe the palette as a system.** Ask each `palette` for (a) base local colors, (b) one saturated accent hue, and (c) how the scheme shifts for night, interiors and emotional peaks, following Stewart's practice of separate color schemes per scene.
4. **Add value structure to the quality bar.** Replace "value separation" in the sequential-art sentence with a concrete requirement: the focal figure separates from the ground by value, faces stay readable at thumbnail size, and line weight varies with depth. Add "book-length repeatability: the look must come from line, shape and color decisions, not one-off process accidents."
5. **Tie story_fit roles to the market.** Require at least one `story_fit_*` candidate to use a core sequential production style with a broad palette. For a children's, middle-grade or YA audience, prefer that option for `story_fit_primary`. Reserve novelty processes for `wildcard`, and only with a stated story link.
6. **Weaken `style_notes` color authority.** This fix is already planned. It is listed here because the research supports treating extracted color notes as mood evidence, not as a palette to obey.

### `_DIVERSITY_FIELDS`, `_portfolio_distance`, `_select_role_portfolio`

7. **Make color categorical in curation** (in progress). Before the change, `_DIVERSITY_FIELDS` compared free-text `palette` with token Jaccard (`_field_distance`). Phrases like "Muted earth tones" and "warm ochre washes" scored as fully distinct, so six warm, low-chroma proofs could still maximize distance. The in-progress categorical `color_strategy` term addresses this. Consider dropping free-text `palette` from `_DIVERSITY_FIELDS` once the categorical term exists, because it rewards different wording rather than different color.
8. **Account for the distance bias toward exotic mediums.** `_medium_tokens` counts shared words. "Ink and flat color" and "ink wash" share "ink" and score 0.8 apart, while "cyanotype" scores 1.0 from everything. Maximizing pairwise distance therefore slightly favors single-word novelty mediums over comic-native ones. Drop stopwords ("and", "with") and either normalize medium into a small family enum or apply a novelty penalty to `wildcard`-only mediums outside the wildcard role.
9. **Add eligibility rules in `_select_role_portfolio`,** alongside `require_illustration_balance` and `require_proportion_diversity`:
   - `require_color_diversity` (in progress): keep it, and add the single-hue cap from item 2.
   - Novelty-process mediums only in `wildcard` unless `medium_restriction` names them.
   - Report unmet requirements with the existing `RuntimeError` message pattern.
10. **Use `_build_avoid_block` for rotation, not a ban.** Rotate novelty processes across regenerations so a cyanotype wildcard does not reappear on every refresh.

### `STYLE_SAMPLE_BRIEF_SYSTEM_PROMPT` and scene selection

11. **Replace the "quiet, characteristic micro-beat" with a pregnant moment.** Use the instant just before a turn: a reaction, discovery or decision that implies what follows without showing the story's climax or a spoiler. Structure the three panels as Establisher (place and cast), Initial (the action begins) and a small Peak (the reaction).
12. **Make panel three a focal face,** large in frame, with one specific readable emotion caused by the moment. Keep "expressive detail" only as a fallback for roster subjects without faces.
13. **Ask for depth and a named key light.** Require at least two depth planes in panel one and a named key light that models the focal face. Keep "do not prescribe color or value range" so each candidate's strategy still owns the palette.
14. **Pick the scene for drama, not order (`style_sample_selection`).** It returns the first scene with one to four known characters. Prefer a scene that has the protagonist, an emotionally marked beat and a distinctive location. Use the scene's beat and type metadata, deterministically and without new model calls, and keep the bounded roster contract.

### Proof constraints (`STYLE_PROOF_ART_CONSTRAINTS`, `STYLE_PROOF_IDENTITY_CONSTRAINTS`, `style_template_for_suggestion`)

15. **Add a legibility clause to both lettering modes:** clear figure–ground value separation; the focal face lit and readable at thumbnail size; line weight heavier on near forms; no texture that hides facial features.
16. **Carry the palette system into the image prompt.** The palette fix is already planned; it should include the accent hue. For single-hue styles, `style_template_for_suggestion` should add a positive-rendering clause: dark line on a light ground with a full value range.
17. **Measure, then tune.** Add an offline Hasler–Süsstrunk colorfulness score and a mean-hue check for each stored proof, in provider-free tests or tooling over existing assets. Log the selected proof's `color_strategy` and medium family to the existing analytics. Author picks across these categories are the real preference data. Mocked tests do not establish image quality, so judge changes by visual review of real proof batches.

## Claims I could not trace to a primary source

- McCloud's Reddit AMA explanation of Pantone 653: cool detachment, and that a saturated color would overwhelm the lines. Reddit was not fetchable, so only the Village Voice and Bookreporter interviews are cited.
- The page-level content of *Understanding Comics*, *Making Comics*, Eisner's *Comics and Sequential Art*, Janson's inking guide, Abel & Madden's color chapters and Gurney's *Color and Light*. These were cited through tables of contents or secondary summaries, or not cited at all.
- Mazzucchelli's own reasons for the *Asterios Polyp* palette, Clowes's for *Ghost World*'s blue, and Jillian Tamaki's for *This One Summer*'s blue. Only critics' readings were found.
- Cohn's experimental result that removing the Peak breaks comprehension (seen in a secondary blog only). Laubrock et al.'s finding that text attracts more attention than images in comic panels (seen through a citing paper only).
- The tonal limits of traditional cyanotype (forum posts and retailer copy only).
- ICv2's full-year 2025 Kids and Adult Top 20 lists (behind ICv2 Pro).
- That recent American comics are converging on manga framing (seen in one secondary review of Cohn's work only).
- The awards history of *The Arrival* and whether *The Sculptor* was a bestseller (not checked).
- Any controlled study of color versus black-and-white comics, or of what makes a single sample page or cover sell. None was found.

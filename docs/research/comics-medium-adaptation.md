# Literary-to-comics adaptation: craft principles and implications for Canary

**Date:** 2026-07-25  
**Status:** Research note  
**Question:** What makes a strong literary-to-comics or graphic-novel
adaptation, and how should an AI-assisted pipeline operationalize those
principles?

## Executive conclusion

A strong comics adaptation is neither an illustrated abridgment nor a test of
how many source sentences survive. It is an interpretation that preserves the
source's important narrative, thematic, tonal, and emotional functions while
re-expressing them through the distinctive resources of comics: selected
moments, juxtaposed images, page and spread composition, reader-supplied
inference, lettering, and the physical page turn.

For Canary, the most important consequence is that source coverage and comics
craft need separate but linked representations:

1. A **source-accountability layer** must prove what happened to every source
   unit and why.
2. An **adaptation layer** must state the function to preserve, not merely copy
   or summarize the prose.
3. A **book-level comics treatment** must allocate scenes, pages, reveals, and
   releases before local panel scripting.
4. **Page and render preflight** must check narrative coherence, reading order,
   lettering integrity, and emotional aftermath—not just image quality.

This directly addresses the *Call of Cthulhu* failures. Broken prose boundaries
should have failed extraction; truncated captions should have failed lettering
validation; scene-local planning should have been subordinate to a book-level
rhythm; and a climax should have been followed by a deliberate release or
reaction rather than allowing the scene's “climax” label to flatten the escape
and aftermath into the same tempo.

## What the sources establish

### 1. Fidelity is a creative constraint, not exhaustive reproduction

Adaptation scholarship treats change as inherent to a story moving between
media. Linda Hutcheon describes adaptation as “repetition without replication”:
the recognizable prior work remains present, but medium, context, and creative
interpretation necessarily change it.[^hutcheon] Jan Baetens distinguishes
plot-transfer or “storytelling” adaptations from medium-specific adaptations
that use comics' own devices to reframe—and sometimes substantially alter—the
source.[^baetens-oxford] His later formulation is especially useful here: a
comic can be faithful without reproducing its source servilely.[^baetens-book]

Creator testimony makes that distinction concrete. Writer/editor Chris Ryall
argues that words and pictures should be “two different sides of the medium”
forming one story, and that the adapter must decide which parts remain relevant
when the work becomes comics. He also warns that visually explicit spectacle
can betray prose horror whose effect depended on concealment.[^ryall] Manu
Larcenet's *The Road* demonstrates another kind of fidelity: he retained the
novel's dialogue, removed captions and sound effects, and sometimes spent three
pages rendering a twelve-line landscape description so readers would “read”
the drawings and the silence.[^larcenet]

**Established principle:** Evaluate fidelity at more than one level. Plot
events matter, but so do viewpoint, tone, theme, uncertainty, motif, emotional
effect, and the source's chosen balance between disclosure and concealment.

**Canary inference:** Each project should have an explicit adaptation brief
listing:

- story promises and themes that must survive;
- indispensable causal events and character turns;
- point of view and acceptable changes to it;
- tonal and formal invariants (for example, ambiguity or withheld horror);
- recurring motifs and exact language worth preserving;
- the desired degree of transformation.

The system should judge omissions and transformations against this brief, not
against word-count retention.

### 2. Selection and omission must preserve function and causality

Scott McCloud frames comics-making as a set of choices: moment, frame, image,
word, and flow. His own description of *Making Comics* starts with choosing
“the right moments—what to include, what to leave out.”[^mccloud] Professional
adapters describe a global rather than page-by-page reading process. Chris
Grine reads a prose scene repeatedly and gathers information revealed later in
the chapter before drawing it; he then uses expressions and staging to carry
internal narration visually.[^grine] Ryall similarly reads the complete source,
identifies natural structural breaks, gives deserving scenes more space, and
condenses or combines others.[^ryall]

Research on visual-narrative inference adds an important limit. Readers can
infer omitted action, but not all omissions are equally benign. In controlled
work, omitted climactic **Peaks** were easier to notice and made sequences less
coherent than omissions of other narrative roles.[^cohn-inference] Thus “the
reader will fill it in” is a craft tool, not permission to remove arbitrary
beats.

**Established principle:** Omit prose that the visual sequence can replace or
that the adaptation intentionally deprioritizes; do not silently remove causal
links, climactic events, orientation needed for comprehension, or the emotional
meaning of a scene.

**Canary inference:** Build an adaptation ledger. Every stable source unit
should receive one or more dispositions:

- `depicted`
- `dialogue`
- `thought`
- `caption`
- `visual_motif`
- `compressed_into`
- `intentionally_omitted`

Each disposition should record the destination beat and the source function
preserved; compression and omission require a reason. Coverage validation
should detect gaps and duplication, while an editorial model judges whether
the adaptation preserves causal, thematic, and emotional function. This ledger
is a production control proposed for Canary, not a standard practice claimed by
the sources.

### 3. Visual substitution must remove redundancy without erasing interiority

Comics distribute meaning between text and image. The modalities can reinforce
one another, alternate responsibility, or create productive tension; neither
text nor image alone necessarily contains the whole narrative.[^iyyer] Ryall
therefore rejects having words and pictures tell the same story twice.[^ryall]
Grine describes converting internal prose into an expression or visual
situation after understanding the whole scene.[^grine] Larcenet goes further:
landscape, silence, weather, and duration carry prose effects without
explanatory captions.[^larcenet]

This does **not** imply “captions are bad.” Captions can preserve a distinctive
narrating voice, interior thought, temporal transitions, irony, or language
whose texture is itself part of the work. Ryall describes captions and carried
dialogue as useful bridges across scene changes and as compression tools.[^ryall]

**Established principle:** Give each piece of information a primary carrier.
Show concrete appearance, action, spatial relation, and visible emotion when
the image can communicate them; retain words when voice, abstraction,
interiority, temporal framing, or deliberate image–text tension is the point.

**Canary inference:** Before writing display copy, classify each source unit's
function and choose a carrier:

| Source function | Likely comics carrier |
|---|---|
| Visible action or environment | Image/sequence |
| Character voice or conflict | Dialogue |
| Distinctive narrator voice | Caption |
| Interior reasoning not legible in behavior | Thought/caption |
| Mood or withheld information | Image, color, absence, silence |
| Passage of time or location change | Transition image/caption/page break |
| Repeated symbolic idea | Visual motif, possibly paired with sparse text |

Then run a redundancy review: if text merely names what the image already
shows, cut or transform it unless repetition is deliberately rhetorical.

### 4. Panels form hierarchical narrative arcs, not flat beat lists

Neil Cohn's Visual Narrative Grammar describes recurring functional roles in
image sequences: **Establisher** (sets up participants), **Initial** (creates
tension), optional **Prolongation**, **Peak** (maximal event), and **Release**
(outcome, reaction, or tension release). These roles can nest: a sequence can
have its own arc while serving as a unit in a larger arc.[^cohn-vng]
Experimental work provides evidence that readers respond to this hierarchical
structure and notice some role omissions—especially missing Peaks—more than
others.[^cohn-distribution][^cohn-inference]

This framework is descriptive, not a mandatory five-panel formula. Establishers
and Prolongations are often dispensable, and comics traditions differ in their
continuity patterns.[^cohn-cross-cultural] It is still a valuable diagnostic:
a sequence made only of important “climax” beats lacks preparation,
differentiation, and release.

**Established principle:** Plan narrative functions at multiple scales:
panel sequence, page, scene, chapter, and book. Preserve reaction and outcome
when they carry emotional meaning. Pacing is the allocation of attention and
space across those functions, not simply a fixed panel count.

**Canary inference:** Adapt in two passes:

1. **Global treatment:** map chapter/book arcs, causal dependencies, character
   changes, reveals, reversals, and aftermath; assign rough page budgets and
   page-turn opportunities.
2. **Local comics script:** select panel moments and lettering within those
   constraints, then send discoveries back to the global treatment if the page
   count changes.

Each beat and page can carry a narrative-role annotation, but validation should
look for coherent arcs rather than demand every role. A `Peak` without an
appropriate `Release` should trigger review when the source includes an
important reaction, consequence, or aftermath.

### 5. The page and spread are narrative units

Comics pacing is spatial and reader-controlled. A page can be scanned as a
whole, while a page turn can withhold information. Graphic novelist Katharine
Woodman-Maynard describes planning spreads rather than isolated pages so that a
suspense beat and its reveal are not visible simultaneously; she demonstrates
how placing both on one spread weakens the intended reaction.[^woodman-maynard]
Ryall likewise describes looking for natural page or issue breaks and
cliffhangers without forcing them.[^ryall]

Page layout also affects navigation. Eye-tracking studies show that panel
outlines are a major guide, while text placement and image content become
important when layouts are ambiguous. Blocked or overlapping layouts caused
more skips and regressions than a standard grid in the tested material, and
41% of first panel fixations landed on text despite text occupying only about
14% of the page.[^kirtley] Cohn and colleagues similarly find that page
navigation depends on the interaction of spatial structure and content rather
than a universal simple Z-path.[^cohn-layout]

**Established principle:** Design for the intended reading path and for the
information visible on the current spread. Use page turns deliberately for
reveal, transition, surprise, or emotional punctuation. Experimental layouts
must earn their complexity and remain navigable.

**Canary inference:** The canonical page specification should record semantic
layout intent—reading order, emphasis, reveal/payoff relation, density, and
spread/page-turn role—without prescribing universal template geometry. The
model may choose exact composition, but render verification should check:

- panel and lettering order;
- ambiguous branches, skips, or regressions;
- whether a reveal leaked onto the preceding spread;
- whether important lettering fights the intended visual path;
- whether emphasis matches narrative importance.

### 6. Lettering is part of storytelling, and copy must remain exact

Lettering is not a late textual overlay. Letterer Nate Piekos describes it as a
“visual soundtrack” that guides the eye through dialogue placement, balloon
form, and sound effects.[^piekos] His script guidance calls for every lettering
item to be numbered and typed (dialogue, off-panel speech, whisper, narration,
time/place caption, voice-over, SFX), with the script acting as the production
touchstone for the creative team.[^piekos-script]

No high-trust source supports truncating prose to fit a balloon. Economy comes
from editorial rewriting and redistribution: show information visually,
shorten a complete thought, split it across intentional beats, or give the
moment more space. Ellipsis can be meaningful punctuation, but it must never be
the accidental residue of character-count clipping.

**Established principle:** Treat wording, balloon type, speaker, order, and
placement as narrative data. Reduce text through adaptation decisions before
lettering, not through mechanical truncation.

**Canary inference:** Store complete canonical display copy as atomic,
ordered lettering items with source provenance and intent. Validate:

- no mid-word or mid-clause clipping;
- no unapproved trailing truncation marks;
- preserved names, quotations, and `must_preserve` facts;
- speaker/type/order fidelity;
- feasible balloon capacity before generation;
- exact OCR comparison after generation.

If copy does not fit, return it to editorial adaptation or page planning. Do
not silently mutate it in `draw` or `finish`.

### 7. Editorial validation must operate at several scales

The sources consistently describe repeated whole-scene or whole-work reading,
comparison against the source, and iterative adjustment rather than a single
forward pass.[^grine][^ryall] Cognitive research also cautions against reducing
quality to local panel transitions: sequence meaning is hierarchical, and page
navigation combines layout and content.[^cohn-vng][^kirtley]

**Canary inference:** Use staged editorial gates:

1. **Source integrity:** sentence/paragraph boundaries, ordered ranges,
   overlap, gaps, and complete intended coverage.
2. **Adaptation accountability:** every source unit has a disposition;
   omissions and compressions preserve declared functions.
3. **Causal and emotional continuity:** goals, discoveries, reactions,
   location/time changes, appearance changes, and consequences remain legible.
4. **Book rhythm:** density variation, scene entrances/exits, page turns,
   reveals, Peaks, Releases, and chapter architecture.
5. **Page preflight:** reading order, redundant text/image, lettering load,
   panel distinctness, and intended emphasis.
6. **Rendered-page verification:** panel count/order, OCR, speaker attribution,
   reference identity, visual continuity, and layout navigation.
7. **Human exception review:** present failures with source evidence and the
   proposed correction, rather than requiring exhaustive inspection of every
   page.

Automated scores should be diagnostic, not a single “adaptation quality”
number. A technically complete adaptation can still misunderstand the source;
a transformative adaptation can omit much while preserving its core.

## Application to the *Call of Cthulhu* failure

### Broken source boundaries

Prose beginning mid-word or ending mid-sentence is not an adaptation judgment;
it is corrupted input. Extraction should create stable sentence- or
paragraph-aligned source units with offsets into the original text. The stage
must fail when ranges split lexical/syntactic units, overlap, arrive out of
order, or leave unintended gaps.

### Truncated narration

Captions that end because a character budget was exhausted violate the
lettering contract. Adaptation should produce complete display thoughts and
link them to their source and purpose. A capacity preflight may ask the
adapter to rewrite, split, visualize, or reallocate a caption, but only a
deliberate editorial choice may change its meaning or punctuation.

### Scene-local planning

Reading and planning one scene at a time hides later context and destroys
book-level proportion. The global treatment should be generated and reviewed
before pages. Scene plans must inherit page budgets, reveal targets, character
arcs, and pacing roles from that treatment.

### Flattened climax and aftermath

Labelling an entire scene “climax” collapses structurally different beats into
one tempo. The Cthulhu sequence should separately represent approach/tension,
revelation or attack, escape, immediate reaction, and psychological aftermath.
Cohn's terminology offers a useful diagnostic: Peaks need not all receive
equal space, and the Release is not disposable when it is the story's emotional
meaning. The planner should reserve decompression after major Peaks when the
source includes consequence or changed internal state.

## Recommended pipeline contract

The following is a Canary design synthesis, not a verbatim workflow prescribed
by any one source.

1. **Extract source units:** stable offsets; sentence/paragraph integrity;
   full coverage validation.
2. **Create the adaptation brief:** transformation level, themes, POV, tone,
   motifs, must-preserve facts/language, target length.
3. **Analyze source functions:** causal event, reveal, characterization,
   atmosphere, interiority, transition, motif, reaction, aftermath.
4. **Build the global treatment:** chapter/book arcs, dependencies, page
   budget, spread rhythm, page-turn reveals, and decompression.
5. **Populate the adaptation ledger:** choose visual/textual carrier and record
   every compression or omission.
6. **Write complete comics beats and lettering:** no geometry yet; stable IDs,
   provenance, narrative roles, emotional state before/after.
7. **Plan pages:** semantic layout intent, reading order, emphasis, density,
   page-turn role, and exact ordered lettering.
8. **Run editorial preflight:** coverage, causality, emotional continuity,
   rhythm, text/image redundancy, and lettering feasibility.
9. **Generate the full page:** render from the frozen canonical page request.
10. **Verify and correct:** OCR and visual checks plus exception-based human
    review; corrections return to the owning canonical layer.

## Caveats and source limitations

- Much canonical comics craft knowledge is in copyrighted books. This report
  cites official author/publisher descriptions and concise quotations rather
  than reproducing those books.
- Direct adapter interviews are valuable first-person evidence but are
  practice accounts, not controlled comparisons of adaptation quality.
- Eye-tracking and narrative-grammar studies typically test short strips or a
  limited set of pages. They support navigation and sequence diagnostics, but
  they do not supply a universal page formula.
- Comics conventions vary across cultures, genres, print formats, and digital
  reading. Canary should treat role annotations and navigation rules as
  review aids, not rigid style enforcement.
- There is little mature research on end-to-end AI literary adaptation into
  finished comics. The pipeline recommendations above are explicit engineering
  inferences from human craft and reading research.

## Bibliography

[^hutcheon]: Linda Hutcheon with Siobhan O'Flynn, *A Theory of Adaptation*,
    2nd ed. (Routledge, 2013), [publisher
    preview](https://www.routledge.com/A-Theory-of-Adaptation/Hutcheon-OFlynn/p/book/9780415539388)
    and [preview text](https://www.taylorfrancis.com/books/mono/10.4324/9780203095010/theory-adaptation-linda-hutcheon-siobhan-flynn).

[^baetens-oxford]: Jan Baetens, “Literary Adaptations in Comics and Graphic
    Novels,” in *The Oxford Handbook of Comic Book Studies* (2019),
    [DOI and abstract](https://doi.org/10.1093/oxfordhb/9780190917944.013.35).

[^baetens-book]: Jan Baetens, *Adaptation et bande dessinée: Éloge de la
    fidélité* (Les Impressions nouvelles, 2020), [publisher
    description](https://editeurssinguliers.be/livre/adaptation-et-bande-dessinee/).

[^ryall]: Erin Underwood, “On Writing Adaptations: An Interview with Graphic
    Novel Writer/Publisher Chris Ryall” (2010), [full
    interview](https://emunderwood.com/2010/12/28/on-writing-adaptations-an-interview-with-graphic-novel-writerpublisher-chris-ryall/).

[^larcenet]: Dean Simons, “Interview: Manu Larcenet on bringing Cormac
    McCarthy's chilling masterpiece *The Road* to the comics page,” *The Beat*
    (2024), [full
    interview](https://www.comicsbeat.com/interview-manu-larcenet-on-bringing-cormac-mccarthys-chilling-masterpiece-the-road-to-the-comics-page/).

[^mccloud]: Scott McCloud, *Making Comics: Storytelling Secrets of Comics,
    Manga and Graphic Novels* (Harper, 2006), [author's official
    description](https://www.scottmccloud.com/2-print/3-mc/index.html).

[^grine]: Shamus Kelley, “Animorphs: A Panel By Panel Comic Breakdown of
    Adapting a Scene From *The Visitor*,” interview with Chris Grine, *Den of
    Geek* (2021), [full
    interview](https://www.denofgeek.com/comics/animorphs-the-visitor-graphic-novel-spoilers-breakdown-chris-grine/).

[^iyyer]: Mohit Iyyer et al., “The Amazing Mysteries of the Gutter: Drawing
    Inferences Between Panels in Comic Book Narratives,” CVPR 2017,
    [paper](https://arxiv.org/abs/1611.05118).

[^cohn-vng]: Neil Cohn, “Visual Narrative Structure,” *Cognitive Science* 37,
    no. 3 (2013): 413–452,
    [author-hosted paper](https://www.visuallanguagelab.com/P/NC_visualnarrative.pdf),
    [DOI](https://doi.org/10.1111/cogs.12016).

[^cohn-distribution]: Neil Cohn, “You're a Good Structure, Charlie Brown: The
    Distribution of Narrative Categories in Comic Strips,” *Cognitive Science*
    38 (2014): 1317–1359,
    [author-hosted paper](https://www.visuallanguagelab.com/P/NC_narrativedistribution.pdf),
    [PubMed record](https://pubmed.ncbi.nlm.nih.gov/24646175/).

[^cohn-inference]: Neil Cohn and Hannah Kutas, “Action starring narratives and
    events: Structure and inference in visual narrative comprehension,”
    *Journal of Cognitive Psychology* 27, no. 7 (2015): 812–828,
    [open-access article](https://pmc.ncbi.nlm.nih.gov/articles/PMC4689435/).

[^cohn-cross-cultural]: Neil Cohn and Ryan Ehly, “Who, Where, and When: A
    Cross-Cultural Analysis of Situational Changes in Comics” (2025),
    [University of California repository](https://escholarship.org/uc/item/84963088).

[^woodman-maynard]: Katharine Woodman-Maynard, “Page Turns: Crafting Suspense
    in Comics” (2024), [creator's illustrated
    essay](https://www.woodmanmaynard.com/blog/2024/12/18/page-turns-crafting-suspense-in-comics).

[^kirtley]: Clare Kirtley, Christopher Murray, Phillip B. Vaughan, and Benjamin
    W. Tatler, “Navigating the Narrative: An Eye-Tracking Study of Readers'
    Strategies When Reading Comic Page Layouts,” *Applied Cognitive Psychology*
    37, no. 1 (2023): 52–70,
    [open manuscript](https://discovery.dundee.ac.uk/files/91155937/Applied_Cognitive_Psychology_2022_Kirtley_Navigating_the_narrative_An_eye_tracking_study_of_readers_strategies_when.pdf),
    [DOI](https://doi.org/10.1002/acp.4018).

[^cohn-layout]: Neil Cohn, Martin Paczynski, Ray Jackendoff, Phillip J.
    Holcomb, and Gina R. Kuperberg, “Navigating Comics: An Empirical and
    Theoretical Approach to Strategies of Reading Comic Page Layouts,”
    *Frontiers in Psychology* 4 (2013),
    [open-access article](https://doi.org/10.3389/fpsyg.2013.00186).

[^piekos]: Nate Piekos, *The Essential Guide to Comic Book Lettering* (Image
    Comics, 2021), [official publisher
    description](https://imagecomics.com/comics/series/the-essential-guide-to-comic-book-lettering).

[^piekos-script]: Nate Piekos, “Comic Script Basics,” Blambot,
    [creator's professional
    guide](https://blambot.com/pages/comic-script-basics).

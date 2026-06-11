# PULP UI/UX Review — Main Findings

> **Superseded (2026-06-11):** the four-station redesign implemented the
> bulk of these findings — see `docs/proposals/four-station-redesign.md`
> for what shipped and the few remaining gaps. Kept for rationale.

## Summary

PULP already has a strong visual identity: editorial, production-oriented, print-room inspired, and distinct from generic SaaS dashboards. The product should keep the cream paper background, black ink typography, red production labels, card-based archive layouts, and stage-based workflow.

The main UX issue is not the visual style. The main issue is that the interface sometimes exposes pipeline internals instead of guiding the user through clear production decisions.

The core product rule should be:

> Each screen must clearly answer: what am I reviewing, what can I change, what happens downstream, and what will it cost?

---

## Product Direction

### Keep

- Cream paper / archive-file background
- Heavy black display typography
- Red action labels and production buttons
- Dark left-side production rail
- Card-based layouts
- Editorial terms like `review`, `rerun`, `accept`, `locked`, `complete`
- Production-console feeling

### Improve

- Make stage purpose clearer
- Show costs before expensive actions
- Show reserved vs actual credit usage consistently
- Make inline edits safe and understandable
- Separate user-facing review data from raw AI/debug data
- Add stronger downstream-impact messaging
- Make expensive generation steps feel deliberate

---

## Design System Foundation

### Visual Personality

PULP should feel like:

- A comic production desk
- A story bible
- A print-room console
- A controlled AI production pipeline
- An editorial archive

It should not feel like:

- A generic AI chat product
- A standard SaaS admin panel
- A playful image generator
- A blank canvas design tool

---

## Recommended Color Semantics

Use the existing palette, but make color meaning more consistent.

| Color | Meaning |
|---|---|
| Black | Final, locked, structural, editorial |
| Red | Primary production action, expensive action, active stage, failure |
| Green | Complete, accepted, safe |
| Yellow | Needs review, reserved credits, pending decisions |
| Beige | Generated, draft, neutral surface |
| Blue | Informational/helper state only |
| Grey | Locked, unavailable, waiting |

Important: red should not carry every kind of meaning. It is currently doing too much.

---

## Typography Guidance

The current typography direction is good. Keep the bold condensed heading style.

Use roughly:

| Use | Treatment |
|---|---|
| Main screen title | Large uppercase display type |
| Stage title | Bold uppercase |
| Section label | Small uppercase letter-spaced |
| Card title | Bold, readable |
| Metadata | Small but high contrast |
| Buttons | Uppercase, letter-spaced |

Some metadata in the current UI is too light and small. Keep the style, but improve contrast.

---

## Revised Stage Naming

The current stage names are stylish, but some are too internal.

Recommended user-facing stages:

| Current | Recommended |
|---|---|
| Extract | Extract |
| Styles | Look & Feel |
| Cast | Cast & Places |
| Adapt | Script |
| Plan | Shot Plan |
| Storyboard | Shot Plan |
| Direct | Prompt Review |
| Draw | Generate Panels |
| Compose | Letter & Compose |
| Export | Export |

Main changes:

- Combine `Plan` and `Storyboard` into `Shot Plan`
- Rename `Direct` to `Prompt Review`
- Rename `Draw` to `Generate Panels`
- Rename `Compose` to `Letter & Compose`

---

## Cost UX Findings

Cost handling is one of the weakest areas right now.

The UI currently mixes:

- Credits
- Ink usage
- Dollar-like values
- Credit holds
- Per-action costs
- Monthly usage
- Reserved credits

This creates unnecessary confusion.

### Recommendation

Use **credits** as the primary currency everywhere inside production flows.

Use dollars only in billing/account views, if needed.

### Three Cost States

Every expensive action should show:

| State | Meaning |
|---|---|
| Estimate | Projected cost before action starts |
| Reserved | Credits temporarily held while work runs |
| Actual | Final cost after completion |

Example copy:

```text
Estimated: 112 credits
Reserved: up to 168 credits
Unused reserved credits return automatically.
```

After completion:

```text
Final cost: 119 credits
Returned: 49 credits
```

### Where Cost Must Appear

Cost should be visible near:

- Rerun Extract
- Rerun Look & Feel
- Rerun Cast
- Rerun Script
- Approve prompts and run Generate Panels
- Regenerate failed panels
- Regenerate individual panel
- Rerun Compose
- Export only if export consumes credits

### Better Cost CTA

Instead of:

```text
Next Stage →
```

Use:

```text
Approve Prompts & Run Generate Panels · Est. 112 credits
```

For individual panel regeneration:

```text
Regenerate Panel · Est. 8 credits
```

---

## Stage Rail Improvements

The left rail is visually strong, but the state language should be clearer.

Instead of only:

```text
OK
WAIT
!
```

Use explicit states:

```text
Complete
Needs review
Ready
2 failed
Waiting
Locked
```

The bottom CTA should be contextual.

Examples:

```text
Continue to Look & Feel
Continue to Cast & Places
Review Shot Plan
Approve Prompts & Run Generate Panels
Fix Failed Panels
Continue to Letter & Compose
Export PDF
```

The credit hold in the rail should be renamed:

```text
7,482 credits reserved for this project
```

Avoid negative numbers like `-2,059 credit hold`.

---

# Add a production cost ledger

On the billing page and per project, use a ledger like:

Action	Stage	Estimate	Reserved	Actual	Returned	Status
Draw 14 panels	Draw	112	168	119	49	Complete
Regenerate panel 04	Draw	8	12	7	5	Complete
Rerun Cast	Cast	20	30	22	8	Complete

This is much clearer than a raw history feed of model calls.

Show cost confidence

Some actions are deterministic-ish. Others depend on model behavior.

Use labels:

Low variance
Usually within estimate
Variable
May reserve more than final cost

For users, this is better than explaining the internal model accounting every time.

---

## Shot Plan Findings

Plan and Storyboard should be combined.

Right now:

- Plan shows layout, importance, page assignment, rough dialogue
- Storyboard shows camera, lighting, mood, panel metadata

These are the same object at different levels of detail.

### Recommendation

Create one stage:

```text
Shot Plan
```

Subtitle:

```text
Panels, layout, shots, dialogue, lighting, and intent.
```

### Views

Use three views over the same data:

```text
Outline | Board | Layout
```

#### Outline

Best for reviewing scene flow.

Shows:

- Scene list
- Beats
- Panel count
- Dialogue/narration summary
- Characters
- Locations

#### Board

Best for reviewing each panel’s intent.

Shows cards with:

- Panel number
- Shot type
- Importance
- Story beat
- Characters
- Location
- Dialogue/narration
- Mood
- Estimated cost

#### Layout

Best for page rhythm.

Shows:

- Page number
- Panel shape
- Panel order
- Hero/accent panels
- Spread rhythm
- Drag/drop ordering

---

## Inline Editing Findings

Inline editing should be consistent across screens.

Do not turn every card into a full form.

Use this pattern:

```text
Click field → edit inline
Click card → open inspector
Ask for change → preview patch → apply
```

### Natural-Language Edit Flow

The user types:

```text
Make Adell feel slightly more frail and contemplative.
```

Then the UI shows a proposed diff:

```diff
Appearance:
- Elderly male, reserved posture, formal attire
+ Elderly male, slightly frail posture, formal attire, more tired expression

Personality tags:
+ contemplative
```

Actions:

```text
Apply changes
Cancel
```

For expensive changes:

```text
Apply and regenerate · Est. 8 credits
```

### Downstream Impact

Every edit should say what it affects.

Examples:

```text
This updates Prompt Review only. No images are regenerated.
```

```text
This updates Shot Plan and Prompt Review. Existing images stay unchanged.
```

```text
This will regenerate Panel 04 only. Estimated cost: 8 credits.
```

---

## Prompt Review Findings

The `Direct` screen should become `Prompt Review`.

This is a critical checkpoint because approval triggers the expensive image generation step.

### Current Issue

Showing one large assembled prompt is useful for debugging, but not ideal for user review.

The user should review structured intent first, raw prompt second.

### Recommended Layout

```text
Prompt Review

Left: scene/panel list
Center: structured prompt parts
Raw prompt: collapsed by default
```

### Prompt Parts

Show:

- Shot
- Characters
- Setting
- Lighting / Mood
- Style
- Constraints
- Reference images
- Raw prompt

### Expensive CTA

Use a clear CTA:

```text
Approve 14 Prompts & Run Generate Panels · Est. 112 credits
```

This screen should strongly communicate:

- How many prompts are being approved
- What generation will cost
- What is being reserved
- Which prompts have warnings
- Whether user can approve all or only safe prompts

---

## Generate Panels Findings

The `Draw` screen should become `Generate Panels`.

The gallery works visually, but it needs stronger review and regeneration support.

### Panel Cards Should Show

- Panel number
- Scene
- Status
- Version
- Actual cost
- Accepted state
- Failed state
- Needs review state

Possible states:

```text
Accepted
Needs review
Failed
Generating
Regenerated
```

### Useful Gallery Filters

```text
All
Accepted
Needs review
Failed
Regenerated
```

### Panel Actions

Each card should offer:

```text
Accept
Edit & Regenerate
Details
Compare
```

---

## Panel Details Modal Findings

The details modal should become a panel review and regeneration cockpit.

### Recommended Tabs

```text
Review | Edit | Prompt | History | Metadata
```

### Review Tab

Answers:

- What was this supposed to depict?
- What image was generated?
- What page/panel uses it?
- Is it accepted?

Show:

- Large image
- Intended beat
- Shot/composition
- Characters
- Location
- Mood
- Dialogue/narration to be added later
- Accept/reject actions

### Edit Tab

Support natural-language changes:

```text
Make her face more consistent with the reference and remove the extra flowers.
```

Quick chips:

```text
Fix likeness
Wider shot
Closer shot
Brighter
Darker
Remove artifact
Match previous panel
Less stylized
```

Then show:

```text
This will regenerate Panel 04 only.
Estimated cost: 8 credits.
Reserved: up to 12 credits.
```

### Prompt Tab

Show editable prompt parts:

- Subject
- Composition
- Setting
- Lighting
- Mood
- Constraints
- Negative constraints
- Reference images

Raw prompt can exist, but should be advanced/collapsed.

### History Tab

Show versions:

```text
v1 · 8 credits · rejected
v2 · 7 credits · accepted
```

Actions:

```text
Compare
Restore
Use as base
```

### Metadata Tab

Show debugging details:

- Model
- Resolution
- Seed
- Prompt version
- Reference images
- Generated at
- Actual credits charged
- Reserved credits returned

---

## Letter & Compose Findings

Compose should be renamed:

```text
Letter & Compose
```

It should be where users arrange pages and add final text.

### Recommended Modes

```text
Canvas | Script | Issues
```

#### Canvas

Current direct editing mode.

Used for:

- Moving bubbles
- Editing narration
- Editing SFX
- Adjusting placement
- Arranging pages

#### Script

Side-by-side reading/checking mode.

Shows:

- Script/dialogue on one side
- Page preview on the other

#### Issues

Production QA mode.

Shows warnings like:

```text
Text overflow
Unreadable contrast
Bubble outside safe area
Missing narration
Unaccepted panel
Low-resolution image
Untranslated text
```

### Inspector Improvements

For selected objects, show:

- Type
- Attached panel
- Text
- Rotation
- Font size
- Alignment
- Layer order
- Bubble style
- Tail target
- Contrast warning
- Delete action

### Late Image Fixes

Users will notice image issues during compose.

Allow:

```text
Replace image
Edit & regenerate
Open in Generate Panels
```

---

## Export Findings

Export should feel like a final production checkpoint, not just another canvas mode.

### Recommended Layout

```text
Export

Main: large spread/page preview
Right: export settings and checks
Bottom/side: page list
```

### Pre-Export Checks

Before PDF/CBZ export, show:

```text
✓ 8 pages composed
✓ 16 panels available
! 2 panels not accepted
! 1 text element outside safe margin
✓ English lettering complete
```

Actions:

```text
Review issues
Export anyway
Export PDF
Export CBZ
```

### Export Settings

Include:

- Format
- Page range
- Quality
- Language
- Theme
- Margins
- Bleed
- Page numbers
- Cover
- Metadata

---

## Main Priorities

### Priority 1: Cost Trust

Add contextual cost information before every expensive action.

### Priority 2: Stage Clarity

Rename internal-feeling stages and make the left rail more explicit.

### Priority 3: Combine Plan + Storyboard

Use a single `Shot Plan` stage with Outline, Board, and Layout views.

### Priority 4: Prompt Review

Replace raw prompt-first UX with structured prompt review and checks.

### Priority 5: Panel Regeneration UX

Make Draw/Generate Panels support natural-language edits, prompt-part edits, version history, and clear cost preview.

### Priority 6: Compose and Export QA

Add issue detection and pre-export checks.

---

## Screen-by-Screen Rule of Thumb

| Screen | User question it should answer |
|---|---|
| Extract | Did we understand the story entities correctly? |
| Look & Feel | Is this the right visual language? |
| Cast & Places | Are these the right visual anchors? |
| Script | Is the adapted script usable for panels? |
| Shot Plan | Is the comic planned correctly before prompting? |
| Prompt Review | Are the expensive image prompts correct? |
| Generate Panels | Are the generated images usable? |
| Letter & Compose | Does the final page read correctly? |
| Export | Is this safe and ready to ship? |

---

## Final Principle

Do not make PULP feel simpler by hiding the production process.

Make it feel safer by making each step explicit:

```text
Review → Edit → Preview impact → Approve → Spend credits
```

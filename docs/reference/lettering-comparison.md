# Project lettering choice and comparison specimens

Status: Current. Decision: [ADR 0022](../adr/0022-project-lettering-choice.md).

The third new-project step requires an explicit `integrated` or `editable` choice.
Both source upload and catalog import persist `Config.lettering_mode`. Omitting it
from non-UI creation retains the editable default. PATCH rejects mode changes;
there is no in-place conversion or new-edition switching UI in this release.
Existing editions, including retained baked editions, keep their frozen profiles.

New integrated profiles send Adapt/Plan copy to Draw, omit software design tokens,
and retain each model's reference/spend boundaries. Editable profiles omit copy
from image requests and use the shared renderer. Look generates integrated proofs
with lettering drawn directly in the artwork, while editable proofs retain generated
lettering designs applied by the shared renderer. Integrated projects hide software
lettering controls. Finish continues
to branch on the edition profile, never the current configuration alone.

## Fairness and provenance

The primary example is The Call of Cthulhu page 26, original render revision 1.
It shows five narration blocks, a speech balloon, dense copy and a detailed statue.
Page 25 is the second example: two speakers, short and long speech balloons, and
narration. Both were existing integrated pages generated with Sunburst. Sources
remain untouched in the user's project.

Both examples are public domain (H. P. Lovecraft). The quick comparison above
the choice offers two views of page 26: Captions (with the live editable demo)
and Translation. There is no sound-effect specimen; the pros and cons describe
action lettering in words.

For each editable study, ImageGen reconstructed the areas occupied by lettering
and balloons, keeping the composition as closely as possible. These are different
generation conditions, **not** a fresh paired production benchmark. The page 25
first pass left empty balloons and boxes, so a second explicit edit removed them.
The final base images were visually inspected for unwanted lettering/shapes.

The exact canonical English strings were copied into typed PageLettering states.
Placement was manually matched to the original pages. EB Garamond and the actual
caption/balloon renderer provide software output, not an AI approximation of it.
The Spanish example is an authored illustrative translation of page 26 using the
identical clean base image and placements. It is not evidence of automatic
translation quality. All text variants pass production overflow/glyph validation;
users still need visual review after translation or edits.

All displayed pages are 1024 × 1536, WebP quality 92, at equal display sizes with
identical crop bounds. Both modes have full-size links and equal choice prominence.
Neither is preselected or labeled as universally better. Preparation limits are
visible directly beneath the images. No generation starts from comparison controls.
The lettering-layer toggle replaces only the editable composite with its exact
clean base image; the integrated image remains unchanged. This exposes the
construction difference without suggesting integrated text can be hidden.

Assets, inputs and exact generation prompts are in
`web/public/lettering-comparison/`; `provenance.json` records the production method.
The comparison is static and available before a project or account-specific
artifact exists. Specimens contain only the selected example pages and derived
artwork, never account IDs or private project paths.

Rebuild editable composites without provider calls or project mutations:

```sh
novel_to_comic/.venv/bin/python scripts/build_lettering_comparison.py
```

This executes the same Chromium font measurement and SVG composition used by the
editor/export. Integrated assets are compressed copies of the original renders.
Base reconstruction is a one-off example-preparation process, not a conversion
feature. A future production quality comparison should independently generate both
modes with the same model, scene, source copy, approved references, style and output
size, record every attempt and manual adjustment, and include multiple page types.

# Dunwich texture propagation

**Status: Current observations; unverified prompt mitigation.** Inspected September 19,
2026. Project `0b6a4e13-093a-445b-8b67-dd647ea00155`, The Dunwich Horror.

## Evidence

Local artifact root: `projects/947150d4-7d2f-4726-a018-5539f933ea56/the-dunwich-horror/`.
Inspected original PNGs, not reader WebP previews: selected `samples/style_3.png`,
`refs/character_style_board.png`, `refs/part0001_char_007/sheet.png`,
`plates/part0001_loc_001.png`, and all nine available Draw renders: pages 1, 2,
26, 32, 42, 45, 53, 57 and 58. Page 50 has a request/failure but no saved render.

The visual symptom is usefully called **cross-material mottling** or **texture
contamination**. These are descriptive labels, not a diagnosis of a model-internal
defect. Larger blotches resemble exaggerated watercolor blooms or stained paper;
their transfer across skin, cloth and sky makes them objectionable.

- The selected proof already has mottled skies, heavily worked dark clothing and
  aged paper. Its prompt explicitly asks for watercolor blooms, sepia paper and
  phenomena emerging from stains. Some texture is intentional art direction.
- The calibration board is predominantly stained, cracked-looking washes and
  dark textured folds. It provides little quiet surface area. This is the most
  conspicuous intermediate escalation in the inspected chain.
- Hoadley's sheet carries similar stains into his face, white neck bands, dark
  clothing and background. The loss of material separation is more diagnostic
  than texture on stones or vegetation alone.
- Page 26 carries blotches across the men's coats; page 42 is especially useful
  for judging skin, clothing, wall and bed material separation; pages 53 and 58
  retain the pattern in faces/clothes alongside dense landscape texture.
- Page 1's landscape closely repeats the location plate, including its texture.
  Its abstract horror panel is a weaker diagnostic because the scene itself asks
  for indistinct forms in darkness.

Metadata records the actual reference chain:

```text
style_3 (no image references)
  ├─ character_style_board → character sheets → Draw
  └─ location plates → Draw
```

The location plate's reference SHA is
`8b62d477d819337dd444419f37df1a667d0b98d4f9a44a9cdb7db395ace3aada`
(style_3); page 1 records the plate SHA
`0c9a8908884559237f067b8cffd99d9d8184a8f787254701fc8d848de12e3e03`.
Character metadata names the calibration board as its style reference.

All ten saved Draw requests include RENDERING FIDELITY v1 and have
`correction: null`; all nine saved images are `render_001.png`. The proof, board,
Hoadley sheet and location plate also contain the existing surface policy.
Therefore this is evidence of the existing prompting safeguard being insufficient
for this example, not of its absence. It does not show a chain of repeated page
edits, nor establish that every successive generation monotonically worsens.

The route is `codex-dev`, configured with source image selector `gpt-image-2`.
Asset provenance explicitly reports the actual image model as unknown. The
reasoning model label `gpt-5.5` is not evidence of the image backend. Do not apply
the earlier direct OpenAI transport's high-quality/size claims to this route.
For example, page 1 requests 1696×2528 but records an actual 1024×1536 PNG;
the development route treats dimensions as intent. This is a separate detail-budget
limitation, not proof of the blotching's cause.

## Implemented hardening

The [compiler](../../novel_to_comic/src/novel_to_comic/compiled_request.py) now
scopes image authority to *intended* rendering and explicitly applies surface
fidelity at the point of reference instruction, replacing unconditional exact
matching and conflict precedence. Deliberate texture remains authorized.

The [calibration prompt](../../novel_to_comic/src/novel_to_comic/stages/s3_cast.py)
asks for quiet tonal fields, clear contours and separate material mark scales,
with paper aging confined to its support. It keeps the people-free calibration
contract rather than restoring a face-bearing style proof as identity evidence.

The [hybrid Draw prompt](../../novel_to_comic/src/novel_to_comic/page_drawing.py)
explicitly separates identity/state/material evidence from additional surface
texture and preserves authorized correction scope. These changes happen before
hashing/freezing. They do not alter selected styles, existing images or frozen
requests, remove references, change models, or submit generations.

## Next mitigation to evaluate

1. Create and approve a cleaner proof that retains the palette and watercolor
   language but uses quieter sky/skin/cloth. Review a new calibration board before
   regenerating affected Cast authorities. Prompt changes alone do not cleanse
   the currently selected reference chain.
2. Expose proof/board surface review before downstream work: material separation,
   readable contours at page size, and no shared blotch field across unrelated
   surfaces. Any automated reviewer should flag uncertainty, not certify quality
   from a texture score or a successful generation.
3. Compare the existing wording and hardened wording using identical reference
   bytes, then test cleaner references as a separate variable. Use page 42 for
   material separation and page 53 for small faces. Review native pixels and the
   same reading size. Record actual output dimensions and known/unknown backend.

No live comparison was performed. Tests establish preservation of prompt and
reference contracts, not improved images. See the [code audit and official
prompting sources](texture-amplification-code-audit.md) and [earlier investigation](image-texture-fidelity.md).

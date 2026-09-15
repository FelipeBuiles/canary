# Hybrid full-page lettering — engineering note

## Contract before this change

Adapt owns exact copy. Plan freezes semantic `ComicPage` records. Draw freezes a
model-specific edition, compiles exact copy into a single complete-page request,
and retains immutable render bytes. Finish normalizes and packages those bytes.
The old Compose system instead assembled panel images and duplicated CSS/tail
layout between Python and React; its interactions depended on panel-pixel offsets.

## Reuse, not restoration

Inspected historical commits c444e568, 3df04499, cecff1c6 and 98c328f3. Retain their
curated fonts, semantic role/preset idea, SVG tails and local Playwright rendering.
Do not restore panel assembly, panel reframing, guessed bubble heights, or separate
client/export typography implementations. The new editor manipulates normalized
page geometry and displays the very SVG used for export. Server-resolved lines are
explicit; browser wrapping has no authority.

## Target contract

New capability profiles explicitly set `exact_visible_lettering=false`. Retained
baked profiles preserve their identities. Reservations are Plan-owned **sidecars**
bound to the existing ComicPage hash: adding default fields to ComicPage itself
would change old content hashes. Mutable lettering lives outside Draw and has its
own copy, locale, style, placement, revision and visual-review identity. Editing
lettering cannot generate an image, mutate Adapt or overwrite a Draw render.

The Pages room gains a lettering workspace, not a ninth pipeline stage. Safe,
explicit saves use optimistic concurrency; preview requests never write state.
Finish composites the selected locale with the same canonical SVG renderer.
Overflow blocks export rather than shrinking unreadably or silently clipping.

No paid generation is required to test this change. Fixture/browser checks verify
software rendering and interactions, not image-model reservation fidelity.

## Verification evidence (2026-09-15)

- Full backend: 1,762 passed, 14 skipped; one Cast-status failure reproduced on
  unchanged `ead22c2c` (`unapproved_style` in `test_cast_asset_routes.py`).
- Full frontend: 461 passed across 76 files. Production TypeScript/Vite build,
  complete ESLint check and documentation reliability check passed.
- Ruff passes all Python files changed here. Repository-wide Ruff also reports
  existing findings on the unchanged baseline; those unrelated files are not
  silently rewritten as part of this feature.
- A real Chromium fixture exercised the actual React workspace and FastAPI
  lettering router: pointer drag, undo and save passed without browser exceptions.
  Desktop and 390px mobile renders were visually inspected; the inspector was
  moved above secondary controls and the mobile grid's intrinsic overflow fixed.
  The isolated browser harness used inline bundles, in-memory browser storage,
  embedded local fonts and a provider-free schematic background. It did not test
  live authentication, deployment, image generation or model reservation fidelity.
- Real Chromium composition plus PDF/CBZ tests preserve source art bytes and
  confirm separate lettering/composite identities. Fit errors never create a
  Draw correction request or spend credits.

Browser previews use cached local font URLs, while export embeds the same bytes;
geometry, glyph selection and explicit line breaks share one SVG implementation.
Saved copy/layout is authoritative; transient dragging scales/moves that SVG for
immediate feedback until the measured preview resolves.

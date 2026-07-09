# Compose panel image reframing

## Goal

Make it practical to refine the crop of generated panel art during Compose
without changing a panel's page geometry, lettering, or layout. Editors must
be able to visually pan and zoom the image within its existing cell.

## Scope

- Fixed panel cells only. This work does not add panel resizing, reordering, or
  freeform page layout editing.
- Existing bubble and SFX editing remains unchanged.
- Framing data must render identically in the Compose canvas, HTML renderer,
  PDF, and CBZ outputs.

## Interaction design

Selecting a panel enters the existing Reframe mode and opens its floating
inspector. In that mode:

- Dragging directly on the panel pans the art within the fixed cell.
- A visible Zoom range control adjusts the art from 100% to 250% and updates
  the canvas immediately.
- `Center image` removes only X/Y pan while retaining the chosen zoom.
- `Reset framing` removes both pan and zoom, restoring the generated default
  crop.
- Escape and selecting another canvas item leave Reframe mode as they do now.

The range control is the primary zoom affordance; this feature deliberately
does not add numeric X/Y or zoom inputs, on-canvas control overlays, or hidden
gesture-only controls.

## Data and rendering

`PagePanel` gains an optional `image_scale` value alongside
`image_offset_x` and `image_offset_y`. A null value represents the default
1x framing; saved values are limited to the supported 1.0--2.5 range.

The page PATCH endpoint accepts `image_scale`, and the TypeScript API type
exposes it. Compose retains the value when it projects existing pages from a
revised layout plan.

The editor previews a local frame state while a drag or range interaction is
underway, then persists the resulting value when the interaction settles. The
same CSS scale custom property is emitted by the web `PanelImage` and the
Python HTML renderer. Scaling stays at or above 1x, so the panel art continues
to cover its cell without exposing empty edges.

## Error handling and reset behavior

Server-side model validation rejects crop scales outside the supported range.
The editor falls back to 1x when legacy or unframed panels have no scale.
Center and reset issue ordinary page patches, so they participate in the
existing optimistic update, undo, and redraw behavior.

## Verification

- Python model tests cover the default, valid, and invalid image scales.
- Page PATCH tests verify persistence of `image_scale` with X/Y offsets.
- Layout projection tests verify that a pre-existing scale is preserved.
- HTML rendering tests verify the exported crop scale property.
- Frontend tests verify the slider preview, committed framing patch, center,
  and full reset behavior.
- Manual browser verification confirms pan and zoom are visible in the canvas
  and match the exported page.

## Success criteria

An editor can select any panel, move the image, zoom it to focus the subject,
center or fully reset the frame, and export a book whose crop exactly matches
the editor preview. No panel cell dimensions or lettering positions change.

# Panel Aspect Contract Design

## Problem

Panel image generation currently receives conflicting shape signals:

- `planned_panels[]` stores a narrative shape such as `shape_intent`,
  `aspect_preference`, and `shot_type`.
- `planned_pages[].panel_geometries[]` stores the actual compose slot geometry.
- `direct/*/panel_NNN.json` derives image dimensions and prompt wording mostly
  from `shot_type`.
- `image-balanced` routes through `litellm_handlers/vertex_multimodal.py`,
  which does not currently pass a size or aspect-ratio constraint to Vertex and
  does not validate the returned image dimensions.

In `the-egg`, `scene_001:panel_005` demonstrates the split:

- panel plan: `shape_intent: rect`, `aspect_preference: 1.0`;
- page slot: `aspect_ratio: 1.5`, landscape;
- direct prompt: `width: 768`, `height: 1024`, plus "vertical panel";
- returned PNG: `1408 x 768`, landscape.

The later compose stage needs predictable panel art shape, so prompt text alone
is not a sufficient contract.

## Goals

- Establish one canonical generation aspect for each planned panel after page
  geometry is known.
- Make prompt text, image dimensions, provider request parameters, output
  validation, and compose metadata all consume that same aspect.
- Preserve the ability to express shot intent such as close-up, portrait, or
  vista without letting shot type override the final compose shape.
- Detect and surface provider shape drift instead of silently accepting an
  image that will crop poorly later.

## Non-Goals

- Do not redesign the page layout algorithm.
- Do not make compose resize page slots to match generated images.
- Do not add legacy migration shims for old artifact schemas beyond tolerant
  reads where existing code already supports them.
- Do not require generated images to match exact pixels for all providers. The
  required invariant is aspect within tolerance, not byte-for-byte dimensions.

## Canonical Data Model

Add explicit generation-shape fields to `PlannedPanel` and `ImagePrompt`:

- `generation_aspect_ratio: float`
- `generation_width: int`
- `generation_height: int`
- `generation_shape: "portrait" | "landscape" | "square"`
- `generation_aspect_source: "page_geometry" | "panel_shape" | "shot_default"`

`generation_aspect_source` is diagnostic. Normal planned panels should use
`page_geometry` once pagination has assigned the panel to a page slot. Fallbacks
are only for partial artifacts, tests, and direct-stage recovery when page
geometry is unavailable.

## Aspect Selection

After `planned_pages` are created, derive each panel's canonical aspect from
the matching `panel_geometries[]` entry:

- Use `panel_geometry.aspect_ratio` when present.
- Otherwise compute `region_width / region_height`.
- Map the ratio to a practical provider size bucket:
  - portrait if ratio < `0.9`;
  - square if `0.9 <= ratio <= 1.15`;
  - landscape if ratio > `1.15`.

Suggested default dimensions:

- portrait: `768 x 1024`
- square: `1024 x 1024`
- landscape: `1536 x 1024` for common 3:2 page slots; wider slots may use
  `1344 x 768`

These dimensions should be centralized in one helper so prompt assembly,
estimation, tests, and regeneration all agree.

## Prompt Assembly

`build_planned_panel_prompt_spec()` should use canonical generation fields when
they exist.

Prompt wording should describe the final frame directly:

- portrait: "vertical portrait frame";
- square: "square frame";
- landscape: "wide horizontal frame".

Shot language remains separate. A close-up in a landscape slot should become
"close-up composed for a wide horizontal frame", not "vertical panel".

For `generation_mode == "master"`, keep flexible crop language, but make it
explicitly compatible with the canonical frame:

> extra margin for flexible crop within a wide horizontal frame

## Provider Enforcement

The LiteLLM HTTP provider already sends a `size` parameter. The
`vertex_multimodal` custom handler must read optional size/aspect params and
apply the strongest constraint supported by the Vertex image model.

Implementation should attempt, in order:

1. If the Google GenAI SDK supports an image aspect ratio field for the target
   model, pass it in `GenerateContentConfig`.
2. Add a compact text preface before the prompt:
   `Output aspect ratio must be landscape (about 7:4). Fill one wide horizontal frame.`
3. After decoding the returned image, inspect dimensions and compare actual
   aspect against requested aspect.

If the output is outside tolerance, the handler should return an error payload
or raise an exception that Canary classifies as a recoverable
`shape_mismatch`.

Initial tolerance:

- accept if actual/requested aspect is within 12%;
- otherwise retry once with stronger aspect wording;
- if retry still fails, write failure metadata and require user regeneration.

## Draw Metadata

Panel image metadata should include:

- requested width/height;
- requested aspect ratio;
- requested shape;
- actual output width/height;
- actual aspect ratio;
- aspect validation status.

This makes later debugging possible without opening the image manually.

## Compose Contract

Compose should read the planned page geometry as it does today. The change is
that draw output should already target that slot aspect. Compose may still crop
or letterbox according to editor settings, but a panel whose output aspect
fails validation should be treated as not ready for final export.

## Regeneration Behavior

Panel regeneration must reuse the same canonical generation fields. It should
not recompute dimensions from `shot_type`, because that can reintroduce the
old mismatch after users regenerate a panel.

If a user edits the page layout later, mark affected panel prompts/images stale
so they can be regenerated against the new geometry.

## Tests

Add focused tests for:

- deriving canonical aspect fields from `planned_pages[].panel_geometries[]`;
- prompt assembly for close-up + landscape slot does not say "vertical panel";
- draw metadata records requested and actual dimensions;
- Vertex handler receives portrait/square/landscape size params and emits
  aspect guidance;
- output validation rejects a returned landscape image for a portrait request;
- regeneration keeps canonical dimensions from page geometry.

## Acceptance Criteria

- For `the-egg` `scene_001:panel_005`, the canonical aspect is landscape
  because page 1 panel geometry is 1.5.
- Its prompt no longer says "vertical panel"; it says the close-up is composed
  for a wide horizontal frame.
- The image request and output metadata agree on the requested aspect.
- If Vertex returns an image outside aspect tolerance, Canary does not silently
  accept it as a completed panel.

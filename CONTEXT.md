# Canary — Domain Glossary

This file defines the project's canonical vocabulary. It is intentionally
implementation-free: runtime contracts, file paths, API routes, model choices,
and UI behavior belong in `docs/reference/`.

When a term conflicts with this glossary, stop and resolve the vocabulary
before changing code or documentation.

## Pipeline concepts

**Stage** — A discrete, resumable unit of the comic-making pipeline. A stage
has a named input/output contract and may pause for user review.

**Checkpoint stage** — A stage whose completed output requires explicit user
approval before the pipeline advances.

**Station** — A user-facing grouping of pipeline work. Stations are a product
concept; they do not rename or merge backend stages.

**Auto step** — Pipeline work that runs without an approval decision and is
presented for inspection when useful.

**Story Bible** — The shared story understanding used by later pipeline work:
characters, locations, scenes, arcs, and props.

**Visual anchor** — A stable physical description attached to a character or
location and used to preserve visual identity across generated images.

**Layout plan** — The planner-owned description of page and panel structure.

**Planned panel** — A panel-level record in a layout plan. It describes the
intended scene, framing, shape, and other visual constraints.

**Panel breakdown** — A downstream description of a planned panel used where
the pipeline still needs a panel-specific projection.

**Image prompt** — The assembled visual instruction for generating a panel
image. Editable source fields and the assembled prompt are distinct concepts.

## Comic editing concepts

**ComicPage** — The editable representation of one comic page, including panel
placement and lettering elements.

**Bubble** — A speech, thought, or narration element placed on a comic page.

**Sfx** — A sound-effect element placed on a comic page.

**Panel flag** — A user's request to revisit a generated panel. Flags support
review-by-exception; they are not the same as approval.

**Panel acceptance** — The legacy concept of explicitly accepting individual
panels. It remains meaningful for compatibility, but current review is based
on panel flags and checkpoint approval.

**Primary ref** — The user's chosen canonical character reference used to
support consistent depiction.

## Project and generation concepts

**Project** — One comic production workspace, from source novel through export.

**Style template** — The project's active visual direction.

**Target language** — The language used for generated creative text in a
project.

**UI localization** — The language used for browser interface text. It is
separate from target language.

**Quality preset** — A named generation-quality choice that selects a coherent
set of model intents.

**Generation job** — An asynchronous unit of asset generation, such as a panel
or character reference regeneration.

**Labs run** — An independent model-experiment run. It is not a pipeline run
and does not advance project pipeline state.

## Historical terms

**Direct checkpoint** — Obsolete terminology for a former approval boundary.
Current product language treats direct as an auto step; references to the old
boundary should be labeled historical.

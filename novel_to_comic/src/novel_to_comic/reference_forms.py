"""Cast reference sheet layouts, one per ``ReferenceForm``.

A ``figure`` sheet is a turnaround: head-and-shoulders close-ups and standing
views on one ground line. It fits people and animals with a fixed anatomy and
a face. For anything else it invents backs, heads and standing poses, and it
repeats one member of a collective instead of showing the group:

- ``form``: one hero depiction plus a material study and an alternate shape or
  motion, for an entity with no fixed front, back or head, or whose identity is
  a material, light or motion.
- ``formation``: the whole group in formation plus member studies, for a
  collective whose identity is its member count and arrangement.

Labs (2026-10-04) showed the wrong form is worse than the turnaround: a
formation of one eye drew twelve eyes, and a form study of a girl invented a
story scene. So ``figure`` is the default and the others are explicit choices.

Every form keeps the hero view in the right two thirds and a close study in the
top-left third, so the sheet's ``full_body`` and ``portrait`` crops stay valid.
"""

from __future__ import annotations

from novel_to_comic.models.appearance import AppearanceState, ReferenceForm

# A single view teaches pages one camera angle and one face. Several neutral
# views let Draw re-stage the character while identity stays fixed.
_FIGURE_LAYOUT = (
    "one clean wide turnaround reference sheet",
    "exactly one character identity",
    "exactly five depictions of that same character",
    "left third, stacked: a head-and-shoulders three-quarter portrait on top and a "
    "head-and-shoulders side profile below it",
    "right two thirds, side by side at the same scale and ground line: full-body front "
    "view, full-body three-quarter view, and full-body back view",
    "the views are simultaneous design views, not different characters and not a "
    "narrative sequence",
)

# The studies show the entity, never a situation: a "characteristic motion" with
# no guard pulled a story scene (a rowing boat) into the sheet.
_NO_SITUATION = "no props, vehicles, scenery or story situation"

# "Material, light or face" let a sheet for a point of light pick "face" and
# borrow one from the style proof. A face is drawn only when the anchor gives one.
_ANCHORED_FACE = "when its anchor gives it one"

_FORM_LAYOUT = (
    "one clean wide form study reference sheet",
    "exactly one character identity",
    "exactly three depictions of that same character",
    "right two thirds: one large hero depiction of the whole entity in its characteristic "
    "shape and orientation, centered; no ground line or standing pose unless the anchor "
    "gives it legs to stand on",
    "left third, stacked: a close study of its defining material, surface or light (its face "
    f"only {_ANCHORED_FACE}) on top, and the whole entity in one characteristic alternate "
    "shape, motion or deformation below it",
    "the depictions are simultaneous design studies of one entity, not different characters "
    f"and not a narrative sequence; {_NO_SITUATION}; never invent a back, head or limbs the "
    "anchor does not give it",
)

_FORMATION_LAYOUT = (
    "one clean wide formation reference sheet",
    "exactly one collective identity whose members share one design",
    "right two thirds: the whole group in its characteristic formation, with the member count "
    "and arrangement the anchor gives, every member fully visible and consistent in design",
    "left third, stacked: a close study of one member's defining material, surface or light "
    f"(its face only {_ANCHORED_FACE}) on top, and one whole member below it",
    "the depictions are simultaneous design studies of one collective, not different characters "
    f"and not a narrative sequence; {_NO_SITUATION}; never invent a back, head or limbs the "
    "anchor does not give it",
)

CANONICAL_LAYOUTS: dict[ReferenceForm, tuple[str, ...]] = {
    "figure": _FIGURE_LAYOUT, "form": _FORM_LAYOUT, "formation": _FORMATION_LAYOUT,
}

# A state sheet becomes the character's authority in every panel of that state,
# so it carries only the changed look: one design stance, no situation. Pose,
# support and anything touching the body come from each panel. The heads keep
# the canonical sheet's crop regions.
_STATE_ONLY_THE_LOOK = (
    "show only how the body, face, hair and clothing look in this state; objects that "
    "pierce, pin, bind or are held, other people, scenery, and the event or situation "
    "that caused the state are left out, keeping only their visible marks on the body"
)

STATE_LAYOUTS: dict[ReferenceForm, tuple[str, ...]] = {
    "figure": (
        "one clean wide appearance-state reference sheet",
        "exactly one character identity",
        "exactly three depictions of that same character",
        "left third, stacked: a head-and-shoulders three-quarter portrait on top and a "
        "head-and-shoulders side profile below it",
        "right two thirds: one full-body front view in a neutral design stance, centered",
        _STATE_ONLY_THE_LOOK,
        "the views are simultaneous design views of a look, not a scene or a pose to copy",
    ),
    "form": (*_FORM_LAYOUT, _STATE_ONLY_THE_LOOK),
    "formation": (*_FORMATION_LAYOUT, _STATE_ONLY_THE_LOOK),
}

# Identity quality for sheets. A figure keeps its facial identity; a form or
# formation keeps its shape, material and light and gains no face it lacks.
IDENTITY_QUALITY: dict[ReferenceForm, str] = {
    "figure": (
        "Preserve the active anchor's age, species, anatomy, and facial identity in the "
        "selected rendering style; avoid accidental distortion, not intentional stylization"
    ),
    "form": (
        "Preserve the active anchor's shape, material, light and anatomy in the selected "
        "rendering style; add no face, head or human figure the anchor does not give it"
    ),
    "formation": (
        "Preserve the active anchor's member design, count, arrangement and anatomy in the "
        "selected rendering style; add no face, head or human figure the anchor does not give it"
    ),
}

PERFORMANCE: dict[ReferenceForm, str] = {
    "figure": (
        "Every view uses a relaxed neutral expression and a resting design pose; acting is "
        "chosen per panel, not by the reference. Only an explicitly described state affect "
        "may change the expression, without exaggeration"
    ),
    "form": "Each depiction shows the entity's own characteristic shape and behavior, not acting for a panel",
    "formation": "Each depiction shows the collective's own characteristic shape and behavior, not acting for a panel",
}

# (composition, visual brief) for a canonical sheet.
CANONICAL_DIRECTION: dict[ReferenceForm, tuple[str, str]] = {
    "figure": (
        "Wide turnaround character reference sheet: two close-ups stacked in the "
        "left third, three full-body views across the right two thirds.",
        "Wide turnaround reference sheet: in the left third, a three-quarter head-and-"
        "shoulders close-up above a side-profile close-up; in the right two thirds, "
        "full-body front, three-quarter, and back views. Neutral expression in every view. "
        "Use the natural posture and complete anatomy specified by the character's visual "
        "anchor, on a plain background.",
    ),
    "form": (
        "Wide form study reference sheet: one large hero depiction in the right two "
        "thirds; a close material study above an alternate-shape study in the left third.",
        "Form study reference sheet: in the right two thirds, the whole entity large "
        "and centered in its characteristic shape; in the left third, a close study of its defining "
        "material or light above the entity in one characteristic alternate shape or motion. Use only "
        "the anatomy the visual anchor gives it, on a plain background.",
    ),
    "formation": (
        "Wide formation reference sheet: the whole group in formation in the right two "
        "thirds; a close member study above one whole member in the left third.",
        "Formation reference sheet: in the right two thirds, every member of the group "
        "in its characteristic formation and number; in the left third, a close study of one member's "
        "defining material or light above one whole member. Use only the anatomy the visual anchor "
        "gives them, on a plain background.",
    ),
}

_STATE_SHOW_ONLY = (
    "Show only how this state looks on the body, face, hair and clothing; leave out objects "
    "that pierce, pin, bind or are held, other people, scenery, and the situation itself, "
    "keeping only their visible marks. The selected style owns rendering."
)

STATE_DIRECTION: dict[ReferenceForm, str] = {
    "figure": (
        "One wide appearance-state reference sheet: in the left third, a head-and-shoulders "
        "three-quarter portrait above a head-and-shoulders side profile; in the right two "
        "thirds, one full-body front view in a neutral design stance compatible with the "
        f"active-state anatomy. {_STATE_SHOW_ONLY} Same active identity and appearance in all "
        "three views, each fully contained within its own region. No text or labels."
    ),
    "form": (
        "One wide form study of this appearance state: in the right two thirds, the whole "
        "entity large and centered in its characteristic shape in this state; in the left third, "
        "a close study of its defining material or light above one characteristic alternate shape "
        f"or motion. {_STATE_SHOW_ONLY} Same active identity in all three depictions, each fully "
        "contained within its own region. No text or labels."
    ),
    "formation": (
        "One wide formation study of this appearance state: in the right two thirds, every member "
        "of the group in its characteristic formation in this state; in the left third, a close "
        f"member study above one whole member. {_STATE_SHOW_ONLY} Same active identity in all "
        "depictions, each fully contained within its own region. No text or labels."
    ),
}


_STATE_ONLY_CHANGED = "Show only the changed look, not the situation or anything touching the body; no text or labels."

STATE_COMPOSITION: dict[ReferenceForm, str] = {
    "figure": (
        "Wide appearance-state reference sheet: a three-quarter close-up above a "
        "side-profile close-up in the left third, and one full-body front view in a "
        "neutral design stance in the right two thirds, using the active anchor's "
        f"anatomy. {_STATE_ONLY_CHANGED}"
    ),
    "form": (
        "Wide form study of this appearance state: one large hero depiction in the right two "
        "thirds; a close material study above an alternate-shape study in the left third, using "
        f"the active anchor's anatomy. {_STATE_ONLY_CHANGED}"
    ),
    "formation": (
        "Wide formation study of this appearance state: the whole group in formation in the right "
        "two thirds; a close member study above one whole member in the left third, using the "
        f"active anchor's anatomy. {_STATE_ONLY_CHANGED}"
    ),
}


_NOT_A_CAST = (
    "People in a style reference are not a cast to choose from: do not copy their "
    "faces, hair, age, or clothing."
)

IDENTITY_DESIGN: dict[ReferenceForm, str] = {
    "figure": (
        f"Design this named individual's own face and silhouette from the canonical facts. {_NOT_A_CAST} "
        "Unspecified details must remain compatible with this individual's age, anatomy, and wardrobe."
    ),
    "form": (
        f"Design this entity's own shape, surface and light from the canonical facts. {_NOT_A_CAST} "
        "Unspecified details must remain compatible with its anatomy and nature. Give it a face, "
        "head or human figure only when its anchor does."
    ),
    "formation": (
        "Design one shared member design and the group's formation from the canonical facts. "
        f"{_NOT_A_CAST} Unspecified details must remain compatible with the members' anatomy and nature."
    ),
}


def reference_form(character, state: AppearanceState | None = None) -> ReferenceForm:
    """The sheet layout for a character, or for one of its appearance states."""
    if state is not None and state.reference_form is not None:
        return state.reference_form
    return character.reference_form

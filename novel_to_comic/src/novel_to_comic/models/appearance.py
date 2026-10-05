"""Appearance catalogs and timelines shared by characters, locations, and props.

Adapt records changes; Plan explicitly assigns each visible entity its state.
Anchors are self-contained, verbatim authorities. Conditioning uses declared
changed facets and identity replacement, never inferred prose keywords.
"""

from typing import Optional, Literal

from pydantic import BaseModel, Field, field_validator

from novel_to_comic.models.asset_id import safe_asset_id

# How a character's Cast reference sheet lays out its views. A turnaround fits a
# fixed anatomy with a face; it invents backs, heads and standing poses for
# anything else, and repeats one member of a collective. See reference_forms.
ReferenceForm = Literal["figure", "form", "formation"]

REFERENCE_FORM_DESCRIPTION = (
    "Cast reference sheet layout. figure (the default): a turnaround for any person or "
    "animal with a fixed anatomy and a face, however unusual. form: one entity with no "
    "fixed front, back or head, or whose identity is a material, light or motion (a "
    "floating eye, a gas creature, a living ribbon). formation: a group whose identity "
    "is its member count and arrangement and whose members share one design (a trio of "
    "dancing hearts, a school of kites); only for identity_kind group. When unsure, figure."
)


class StoryPosition(BaseModel):
    """A point in story time: a scene plus an optional 1-indexed beat.

    ``beat=None`` means "scene start" and sorts before any numbered beat in the
    same scene.
    """

    scene_id: str
    beat: Optional[int] = None


class Transition(BaseModel):
    """Descriptive annotation of the moment a new state begins.

    NEVER consumed by the resolver — it only labels the boundary for narration
    and inspection, and keeps the model forward-compatible with an
    event-sourced design. ``cause`` is stored but currently unread.
    """

    label: str  # "hands severed"
    depicted_at: Optional[StoryPosition] = None  # where the change is SHOWN
    cause: Optional[str] = None  # stored-but-unread for now


class AppearanceState(BaseModel):
    """One distinct look of a character.

    ``visual_anchor`` is SELF-CONTAINED: it fully describes the character in
    this state and replaces the base ``Character.visual_anchor`` when active —
    never a delta, never mixed with another state's tags. ``visually_significant``
    flags a state worth its own generated reference image (a body
    transformation, not a minor wardrobe note).
    """

    id: str  # entity-scoped, e.g. "silver"
    _safe_id = field_validator("id")(safe_asset_id)
    label: str  # human label, e.g. "Silver hands"
    visual_anchor: str
    visually_significant: bool = False
    # Optional stable demeanor specific to this appearance state. Transient
    # beat-level reactions still belong in page-level acting direction.
    baseline_affect: Optional[str] = None
    # True only when this state explicitly matches the canonical visual look.
    # Reference selection must never infer equivalence from an id or label.
    canonical_equivalent: bool = False
    # Optional authored continuity rule for this state: what the image model
    # must preserve and must NOT revert to its default prior, plus how scenes
    # should be staged to stay consistent. Generic across entities — e.g. a lost
    # limb ("no hands; never depict gripping; acts via mouth or stumps"), a
    # prosthetic ("rigid polished silver, not flesh"), or a drained lake ("empty
    # cracked mud, not water"). Injected as a hard constraint and into the brief
    # pass whenever this state is the active, visually-significant look.
    continuity_guard: Optional[str] = None
    changed_facets: tuple[Literal[
        "age", "hair", "face", "build", "anatomy", "clothing", "damage",
        "weather", "light", "water_level", "architecture", "landmarks",
        "materials", "atmosphere", "shape", "contents", "color",
    ], ...] = Field(default=(), description=(
        "Every facet this state changes from the base look. Include face when the face, eyes "
        "or expression change, are hidden or are gone (death, unconsciousness, a mask, a body "
        "dissolved or reshaped); otherwise reference images restore the default face. Include "
        "shape when the body no longer has its usual form."))
    replaces_identity: bool = False
    # Characters only: a state that changes the body plan (a person turned to
    # mist) may need another sheet layout. None keeps the character's own form.
    reference_form: Optional[ReferenceForm] = Field(default=None, description=(
        "Characters only; null for locations and props. Set only when this state changes "
        "the body plan enough to need another sheet layout; null keeps the character's. "
        + REFERENCE_FORM_DESCRIPTION))



class StateActivation(BaseModel):
    """Binds a state to a point in story time.

    The active state at a panel is the activation with the greatest position
    ``<=`` the panel's position. Before the first such activation, the base
    look applies. Each activation is itself a transition (the annotation rides
    along on ``transition``).
    """

    state_id: str
    at: StoryPosition
    transition: Optional[Transition] = None

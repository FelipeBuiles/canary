"""Appearance catalogs and timelines shared by characters, locations, and props.

Adapt records changes; Plan explicitly assigns each visible entity its state.
Anchors are self-contained, verbatim authorities. Conditioning uses declared
changed facets and identity replacement, never inferred prose keywords.
"""

from typing import Optional, Literal

from pydantic import BaseModel, field_validator

from novel_to_comic.models.asset_id import safe_asset_id


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
    ], ...] = ()
    replaces_identity: bool = False



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

"""Pydantic models for the Story Bible — the central pipeline artifact."""

import re
from typing import Any, Optional

from pydantic import BaseModel, field_validator

from novel_to_comic.models.appearance import AppearanceState, StateActivation


class CharacterRelationship(BaseModel):
    character_id: str
    relationship: str  # "partner", "antagonist", "sibling", etc.


class Character(BaseModel):
    id: str  # "char_001"
    name: str  # "Elena Vasquez"
    visual_anchor: str  # Strict comma-separated physical tags. Injected verbatim at the very start of identity.
    age_range: str  # "early 30s"
    gender: str
    distinguishing_features: list[str]  # ["jagged scar on left cheek"]
    # Stable, low-intensity demeanor only (for example "guarded and watchful").
    # Scene reactions belong in page-level acting direction, never visual_anchor.
    baseline_affect: str | None = None
    default_outfit: str
    relationships: list[CharacterRelationship] = []
    first_appearance_scene: str  # "scene_001"
    appearance_states: list[AppearanceState] = []
    # Alternate looks this character takes on mid-story (e.g. stumps, silver
    # hands, restored). Each anchor is self-contained. Empty = one stable look.
    appearance_timeline: list[StateActivation] = []
    # Ordered transitions into the states above. The look before the first
    # activation at-or-before a panel is the base visual_anchor. Resolved per
    # page by explicit adaptation and planning state — never by text matching.

    @field_validator("distinguishing_features", mode="before")
    @classmethod
    def coerce_features_to_list(cls, v: Any) -> list[str]:
        """Accept a comma-separated string in place of a list."""
        if isinstance(v, str):
            return [f.strip() for f in v.split(",") if f.strip()]
        return v


class Location(BaseModel):
    id: str  # "loc_001"
    name: str  # "The Bunker"
    visual_anchor: str  # Base-state tags. Used when no activation resolves.
    time_of_day: Optional[str] = None  # "night", "dawn", etc.
    mood: str  # "tense", "warm", "desolate"
    appearance_states: list[AppearanceState] = []
    # Alternate physical states this place takes on mid-story (pre/post
    # collapse, dried moat, interior). Each anchor is self-contained — never
    # mix pre/post in one. Empty = one stable look. State ids must extend the
    # parent location id (e.g. "loc_001_pre") so generated plates never collide.
    appearance_timeline: list[StateActivation] = []
    # Ordered transitions into the states above, resolved per panel by
    # explicit adaptation and planning state — the same mechanism as characters.


class TransientObject(BaseModel):
    """A story-critical visual element that appears in only one scene.

    Distinct from Prop (recurring across 3+ scenes). Transient objects are
    things like a severed head visible for one beat, a floating alien text
    overlay, a single cigarette. They carry visual_anchor identity but are
    scoped to one scene so the planner does not over-promote them into
    every panel.
    """
    id: str  # "trans_001"
    name: str  # "Mrs. Parsons's severed head"
    visual_anchor: str  # 1-2 sentences describing the object
    appears_in_beats: list[int] = []  # 1-indexed beat numbers within the scene (optional)


class Scene(BaseModel):
    id: str  # "scene_001"
    chapter: int
    title: str
    location_id: str
    character_ids: list[str]
    summary: str  # 2-3 sentence summary
    scene_type: str  # "action", "dialogue", "emotional", "transition"
    narrative_beat: str  # "inciting_incident", "climax", "resolution", etc.
    source_start_quote: str  # verbatim opening sentence of this scene in the novel text
    # Per-character and per-location appearance change is modeled on the entity
    # itself (appearance_states + appearance_timeline), resolved per panel by
    # adaptation chronology — not as per-scene override fields.
    transient_objects: list[TransientObject] = []
    # Story-critical visual elements scoped to this scene only.


class NarrativeArc(BaseModel):
    act: int  # 1, 2, 3
    title: str
    scenes: list[str]  # Scene IDs in this act
    turning_point: Optional[str] = None

    @field_validator("act", mode="before")
    @classmethod
    def coerce_act_to_int(cls, v: Any) -> int:
        """Accept 'Act 1', 'act_1', 'ACT 2', etc. in place of a bare integer."""
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            match = re.search(r"\d+", v)
            if match:
                return int(match.group())
        return int(v)

    @field_validator("title", mode="before")
    @classmethod
    def default_title(cls, v: Any) -> str:
        """Accept missing title — will be filled in by normalizer if needed."""
        return v or ""

    @field_validator("scenes", mode="before")
    @classmethod
    def coerce_scenes_to_list(cls, v: Any) -> list[str]:
        """Accept a single scene id string in place of a list."""
        if isinstance(v, str):
            return [v] if v else []
        return v if v is not None else []


class Prop(BaseModel):
    """A key physical object that recurs across scenes and must look consistent."""
    id: str   # "prop_001"
    name: str  # "The Monkey's Paw"
    visual_anchor: str  # What it looks like — injected verbatim into every panel prompt that shows it
    first_appearance_scene: Optional[str] = None
    appearance_states: list[AppearanceState] = []
    appearance_timeline: list[StateActivation] = []


class StoryBible(BaseModel):
    title: str
    author: str
    total_scenes: int
    characters: list[Character]
    locations: list[Location]
    scenes: list[Scene]
    narrative_arcs: list[NarrativeArc]
    style_notes: Optional[str] = None
    props: list[Prop] = []  # Key recurring objects — monkey's paw, magic ring, etc.

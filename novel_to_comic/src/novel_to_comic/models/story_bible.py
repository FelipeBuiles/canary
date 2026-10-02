"""Pydantic models for the Story Bible — the central pipeline artifact."""

import re
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from novel_to_comic.models.appearance import AppearanceState, StateActivation
from novel_to_comic.models.asset_id import safe_asset_id
from novel_to_comic.workspace import FIRST_PART_ID

# "extracted" entities come from the source; "author" entities were added by
# the author in the Story Bible editor and carry no extraction evidence.
EntityOrigin = Literal["extracted", "author"]


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
    # Other names this character goes by. Merging records the absorbed name
    # here so later parts' extraction resolves it to this ID.
    aliases: list[str] = []
    origin: EntityOrigin = "extracted"

    _safe_id = field_validator("id")(safe_asset_id)
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
    aliases: list[str] = []
    origin: EntityOrigin = "extracted"

    _safe_id = field_validator("id")(safe_asset_id)
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
    # The part whose source text contains this scene; its offsets and opening
    # quote refer to that part's text.
    part_id: str = FIRST_PART_ID
    chapter: int
    title: str
    location_id: str
    character_ids: list[str]
    summary: str  # 2-3 sentence summary
    scene_type: str  # "action", "dialogue", "emotional", "transition"
    narrative_beat: str  # "inciting_incident", "climax", "resolution", etc.
    source_start_quote: str  # verbatim opening sentence of this scene in the novel text
    # Deterministic Extract provenance; disambiguates repeated opening sentences.
    source_start_offset: int | None = Field(default=None, ge=0)
    # Per-character and per-location appearance change is modeled on the entity
    # itself (appearance_states + appearance_timeline), resolved per panel by
    # adaptation chronology — not as per-scene override fields.
    transient_objects: list[TransientObject] = []
    # Story-critical visual elements scoped to this scene only.


class NarrativeArc(BaseModel):
    # Acts are organized per part: each part has its own three acts.
    part_id: str = FIRST_PART_ID
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
    aliases: list[str] = []
    origin: EntityOrigin = "extracted"

    _safe_id = field_validator("id")(safe_asset_id)


class ExcludedEntity(BaseModel):
    """An entity the author removed; later extraction must not recreate it."""

    kind: Literal["character", "location", "prop"]
    name: str
    aliases: list[str] = []


class StoryBible(BaseModel):
    # Incremented by every author edit; edits carry the revision they read.
    revision: int = Field(default=1, ge=1)
    title: str
    author: str
    total_scenes: int
    characters: list[Character]
    locations: list[Location]
    scenes: list[Scene]
    narrative_arcs: list[NarrativeArc]
    style_notes: Optional[str] = None
    props: list[Prop] = []  # Key recurring objects — monkey's paw, magic ring, etc.
    excluded_entities: list[ExcludedEntity] = []


_EDITOR_BOOKKEEPING: dict = {
    "revision": True,
    "excluded_entities": True,
    "characters": {"__all__": {"origin"}},
    "locations": {"__all__": {"origin"}},
    "props": {"__all__": {"origin"}},
}


def story_bible_context(bible: StoryBible) -> dict:
    """The Story Bible as model or lineage context, without editor bookkeeping.

    Edit revisions, removal records, and entity origin describe how the Bible
    was maintained, not the story, so they never reach a prompt or a hash.
    """

    return bible.model_dump(mode="json", exclude=_EDITOR_BOOKKEEPING)


def part_story_bible(bible: StoryBible, part_id: str) -> StoryBible:
    """The Story Bible as one part's adaptation sees it.

    Only the part's scenes and acts, the characters on its rosters and the
    places it uses are in view, so a part never adapts another part's scenes
    or stages a character who is only mentioned. Props stay available, and
    entities keep their full appearance catalogs and timelines so states
    carried in from earlier parts remain visible.
    """

    scenes = [scene for scene in bible.scenes if scene.part_id == part_id]
    rostered = {cid for scene in scenes for cid in scene.character_ids}
    places = {scene.location_id for scene in scenes}
    view = bible.model_copy(deep=True)
    view.scenes = [scene.model_copy(deep=True) for scene in scenes]
    view.total_scenes = len(scenes)
    view.narrative_arcs = [arc for arc in view.narrative_arcs if arc.part_id == part_id]
    view.characters = [c for c in view.characters if c.id in rostered]
    for character in view.characters:
        character.relationships = [rel for rel in character.relationships if rel.character_id in rostered]
    view.locations = [loc for loc in view.locations if loc.id in places]
    return view

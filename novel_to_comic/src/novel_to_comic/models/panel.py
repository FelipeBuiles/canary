"""Pydantic models for panel breakdowns."""

from typing import Any, Optional

from pydantic import BaseModel, field_validator


class DialogueLine(BaseModel):
    character_id: Optional[str] = None  # None for narration (no speaker)
    text: str
    type: str  # "speech", "thought", "narration"

    @field_validator("character_id", mode="before")
    @classmethod
    def coerce_empty_to_none(cls, v: Any) -> Optional[str]:
        if v == "" or v == 0:
            return None
        return v


class PanelBreakdown(BaseModel):
    scene_id: str
    panel_number: int  # 1-indexed within scene
    shot_type: str  # "close-up", "medium", "wide", "extreme-wide", "over-shoulder"
    camera_angle: str  # "eye-level", "low-angle", "high-angle", "dutch-angle", "bird-eye"
    characters_present: list[str]  # Character IDs
    character_actions: dict[str, str]  # char_id -> "drawing sword"
    character_expressions: dict[str, str]  # char_id -> "determined"
    character_positions: dict[str, str]  # char_id -> "left foreground"
    background_description: str
    lighting: str  # "harsh overhead", "warm sunset"
    mood: str  # "tense", "hopeful"
    dialogue: list[DialogueLine] = []
    sfx: Optional[str] = None  # "BOOM", "CRACK"
    transition_type: Optional[str] = None  # "smooth_continuation", "match_cut", "hard_cut"
    transition_note: Optional[str] = None  # "smash cut", "fade"


class ScreenplayBeat(BaseModel):
    type: str  # "action", "dialogue", "sfx", "transition"
    character_id: Optional[str] = None
    content: str
    direction: Optional[str] = None
    transition_type: Optional[str] = None  # "smooth_continuation", "match_cut", "hard_cut"


class Screenplay(BaseModel):
    scene_id: str
    location_id: str
    characters: list[str]
    beats: list[ScreenplayBeat]

"""Pydantic models for panel breakdowns."""

from typing import Any, Optional

from pydantic import BaseModel, field_validator

from novel_to_comic.models.comic_page import normalize_sfx_text


class DialogueLine(BaseModel):
    character_id: Optional[str] = None  # None for narration (no speaker)
    text: str
    type: str  # "speech", "thought", "narration"
    source_beat_id: Optional[str] = None
    source_text: Optional[str] = None
    narration_mode: Optional[str] = None
    preferred_zone: Optional[str] = None

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
    sfx: list[str] = []  # bare onomatopoeia, e.g. ["BOOM", "CRACK"]
    transition_type: Optional[str] = None  # "smooth_continuation", "match_cut", "hard_cut"
    transition_note: Optional[str] = None  # "smash cut", "fade"

    @field_validator("sfx", mode="before")
    @classmethod
    def _migrate_sfx(cls, v: Any) -> list[str]:
        if v is None:
            return []
        if isinstance(v, str):
            cleaned = normalize_sfx_text(v)
            return [cleaned] if cleaned else []
        if isinstance(v, list):
            out: list[str] = []
            for item in v:
                if not isinstance(item, str):
                    continue
                cleaned = normalize_sfx_text(item)
                if cleaned:
                    out.append(cleaned)
            return out
        return []


class ScreenplayBeat(BaseModel):
    type: str  # "action", "dialogue", "narration", "sfx", "transition"
    character_id: Optional[str] = None
    content: str
    source_text: Optional[str] = None  # Exact source prose for adapted narration captions
    direction: Optional[str] = None
    transition_type: Optional[str] = None  # "smooth_continuation", "match_cut", "hard_cut"
    narration_reason: Optional[str] = None


class Screenplay(BaseModel):
    scene_id: str
    location_id: str
    characters: list[str]
    beats: list[ScreenplayBeat]

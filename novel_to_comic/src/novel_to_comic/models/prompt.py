"""Pydantic models for image prompts."""


from pydantic import BaseModel, Field


class PromptSubject(BaseModel):
    character_id: str | None = None
    name: str
    identity: str
    action: str = ""
    expression: str = ""
    position: str = ""


class ImagePrompt(BaseModel):
    prompt_version: int = 1
    planned_panel_id: str | None = None
    scene_id: str
    panel_number: int
    generation_mode: str | None = None
    shape_intent: str | None = None
    crop_policy: str | None = None
    transition_in: str | None = None
    transition_out: str | None = None
    has_narration_caption: bool = False
    narration_mode: str | None = None
    preferred_caption_zone: str | None = None
    full_prompt: str = ""
    style: str | None = None
    composition: str | None = None
    setting: str | None = None
    lighting: str | None = None
    mood: str | None = None
    subjects: list[PromptSubject] = Field(default_factory=list)
    key_objects: list[str] = Field(default_factory=list)
    visual_requirements: list[str] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    constraints: str | None = None
    reference_image_paths: list[str] = Field(default_factory=list)  # Project-relative paths to character ref images
    width: int
    height: int
    steps: int
    continuity_note: str | None = None

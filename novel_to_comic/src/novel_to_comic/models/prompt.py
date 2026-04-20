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
    scene_id: str
    panel_number: int
    full_prompt: str = ""  # v2+: compact panel prompt body, excluding current style
    style: str | None = None
    composition: str | None = None
    setting: str | None = None
    lighting: str | None = None
    mood: str | None = None
    subjects: list[PromptSubject] = Field(default_factory=list)
    props: list[str] = Field(default_factory=list)
    constraints: str | None = None
    reference_image_paths: list[str] = Field(default_factory=list)  # Paths to character ref images for multi-ref
    negative_prompt: None = None  # ALWAYS None. FLUX.2 does not support negative prompts.
    width: int
    height: int
    steps: int
    guidance_scale: float
    continuity_note: str | None = None  # Narrative chain from previous panel

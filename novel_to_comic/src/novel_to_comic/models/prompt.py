"""Pydantic models for image prompts."""


from pydantic import BaseModel


class ImagePrompt(BaseModel):
    scene_id: str
    panel_number: int
    full_prompt: str  # The complete assembled prompt string
    reference_image_paths: list[str] = []  # Paths to character ref images for multi-ref
    negative_prompt: None = None  # ALWAYS None. FLUX.2 does not support negative prompts.
    width: int
    height: int
    steps: int
    guidance_scale: float

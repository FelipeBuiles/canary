"""Config view and edit."""

from fastapi import APIRouter, Depends, HTTPException

from novel_to_comic.config import LANGUAGE_NAMES, save_config

from ..deps import get_project

router = APIRouter()

# Fields that should never be returned or set via the API
_SECRET_FIELDS = {
    "litellm_api_key",
}


@router.get("/")
def get_config(project=Depends(get_project)):
    project_dir, config, state = project
    data = config.model_dump()
    # Mask secrets: show whether they're set, not the values
    for key in _SECRET_FIELDS:
        data[key] = "***" if data.get(key) else ""
    return data


@router.patch("/")
def update_config(body: dict, project=Depends(get_project)):
    project_dir, config, state = project

    # Reject attempts to set API keys via the web UI
    for key in _SECRET_FIELDS:
        if key in body:
            raise HTTPException(400, f"Cannot set '{key}' via the web UI. Use .env or environment variables.")

    # Apply updates
    for key, value in body.items():
        if hasattr(config, key):
            if key == "target_language" and value not in LANGUAGE_NAMES:
                raise HTTPException(400, "target_language must be one of: en, es, fr")
            if key == "quality_preset" and value is not None:
                valid_presets = {"fast", "balanced", "quality"}
                if value not in valid_presets:
                    raise HTTPException(400, f"quality_preset must be one of: {', '.join(sorted(valid_presets))}, or null")
            setattr(config, key, value)

    save_config(config, project_dir)
    return get_config(project=(project_dir, config, state))

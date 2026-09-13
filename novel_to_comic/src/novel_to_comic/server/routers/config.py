"""Config view and edit."""

from fastapi import APIRouter, Depends, HTTPException, Request

from novel_to_comic.config import LANGUAGE_NAMES, image_model_aliases, save_config

from ..deps import get_project
from ..auth import get_current_user

router = APIRouter()

# Fields that should never be returned or set via the API
_SECRET_FIELDS = {
    "litellm_api_key",
}

# Only these fields may be updated via the PATCH endpoint
_SETTABLE_FIELDS = {
    "target_language",
    "dev_mode",
    "image_quality",
    "image_steps",
    "negative_prompt",
    "parallel_batch_size",
    "max_concurrent_requests",
    "cost_limit_usd",
    "flux_guidance_scale",
}


@router.get("/")
def get_config(project=Depends(get_project)):
    project_dir, config, state = project
    data = config.model_dump()
    # Mock replay is an operator-only local facility, not an end-user setting.
    data.pop("mock_mode", None)
    data.pop("mock_model_base_url", None)
    # Mask secrets: show whether they're set, not the values
    for key in _SECRET_FIELDS:
        data[key] = "***" if data.get(key) else ""
    data["image_model_aliases"] = list(image_model_aliases())
    return data


@router.patch("/")
def update_config(body: dict, request: Request, project=Depends(get_project), user_id: str = Depends(get_current_user)):
    project_dir, config, state = project

    # Reject attempts to set API keys via the web UI
    for key in _SECRET_FIELDS:
        if key in body:
            raise HTTPException(400, f"Cannot set '{key}' via the web UI. Use .env or environment variables.")

    from novel_to_comic.model_catalog import STAGE_FIELDS
    forbidden = set(STAGE_FIELDS.values()) | {"quality_preset", "image_provider", "fallback_image_model"}
    if forbidden.intersection(body):
        raise HTTPException(400, "Use dev_model_selections for local project model choices.")

    # Work on a new snapshot; a rejected edit must not affect running jobs.
    config = config.model_copy(deep=True)
    if "dev_model_selections" in body:
        from ..account_models import account_config, model_settings_enabled
        from novel_to_comic.model_catalog import validate_selections

        if not model_settings_enabled():
            raise HTTPException(403, "Project model choices require local development mode.")
        previous_draw_model = config.draw_model
        try:
            # Replace the override map: omitted stages inherit account settings.
            config.dev_model_selections = validate_selections(body["dev_model_selections"])
            config = account_config(config, request.app.state.projects_dir, user_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        if config.draw_model != previous_draw_model:
            from novel_to_comic.target_artifacts import TargetArtifacts

            if TargetArtifacts(project_dir).book_edition_path.exists():
                raise HTTPException(409, "Changing the Draw model requires a new edition or project. Other model choices can still be updated.")

    # Apply updates
    for key, value in body.items():
        if key not in _SETTABLE_FIELDS:
            continue
        if key == "target_language" and value not in LANGUAGE_NAMES:
            raise HTTPException(400, "target_language must be one of: en, es, fr")
        setattr(config, key, value)

    save_config(config, project_dir)
    return get_config(project=(project_dir, config, state))

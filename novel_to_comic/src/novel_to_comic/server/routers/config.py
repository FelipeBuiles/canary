"""Config view and edit."""


from fastapi import APIRouter, Depends, HTTPException, Request

from novel_to_comic.config import LANGUAGE_NAMES, image_model_aliases, save_config

from ..deps import get_project
from ..auth import get_current_user
from ..runtime_environment import app_environment

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
    "parallel_batch_size",
    "max_concurrent_requests",
    "cost_limit_usd",
}


@router.get("/")
def get_config(project=Depends(get_project)):
    project_dir, config, state = project
    data = config.model_dump()
    from novel_to_comic.lettering.service import project_lettering_mode
    from novel_to_comic.target_artifacts import TargetArtifacts

    data["lettering_mode"] = project_lettering_mode(TargetArtifacts(project_dir), config)
    # Mock replay is an operator-only local facility, not an end-user setting.
    data.pop("mock_mode", None)
    data.pop("mock_model_base_url", None)
    # Mask secrets: show whether they're set, not the values
    for key in _SECRET_FIELDS:
        data[key] = "***" if data.get(key) else ""
    data["image_model_aliases"] = list(image_model_aliases())
    return data


@router.patch("/", openapi_extra={'x-canary-action': {'spends': False, 'dispatches': False}})
def update_config(body: dict, request: Request, project=Depends(get_project), user_id: str = Depends(get_current_user)):
    project_dir, config, state = project
    if "lettering_mode" in body and body["lettering_mode"] != config.lettering_mode:
        raise HTTPException(409, "Choose lettering when creating a project. Switching requires a new project and new page generation.")

    if "dev_mode" in body and app_environment() == "production":
        raise HTTPException(403, "Dev / demo mode cannot be set in production.")

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
        try:
            # Replace the override map: omitted stages inherit account settings.
            proposed = body["dev_model_selections"]
            if not isinstance(proposed, dict):
                raise ValueError("selections must be an object")
            # An unrelated edit may send back a retired choice that was saved
            # before the catalog changed. Keep that exact value in the file;
            # only newly selected stage/model pairs need current validation.
            validate_selections({stage: model for stage, model in proposed.items()
                                 if config.dev_model_selections.get(stage) != model})
            config.dev_model_selections = proposed
            config = account_config(config, request.app.state.projects_dir, user_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    # Apply updates
    for key, value in body.items():
        if key not in _SETTABLE_FIELDS:
            continue
        if key == "target_language" and value not in LANGUAGE_NAMES:
            raise HTTPException(400, "target_language must be one of: en, es, fr")
        setattr(config, key, value)

    # Validate edition-derived presentation before committing the settings edit.
    response = get_config(project=(project_dir, config, state))
    save_config(config, project_dir)
    return response

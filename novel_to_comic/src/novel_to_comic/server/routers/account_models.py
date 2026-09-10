"""Authenticated, development-only model settings for the whole account."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict

from novel_to_comic.codex_dev import selector_available
from novel_to_comic.model_catalog import FUNDING_GROUPS, STAGE_FIELDS, STAGE_LABELS, allowed_models, models
from ..account_models import model_settings_enabled, read_selections, update_selections
from ..auth import get_current_user

router = APIRouter()


class ModelSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selections: dict[str, str]


def _require_development() -> None:
    if not model_settings_enabled():
        raise HTTPException(403, "Model settings are available only on a development server.")


def _payload(selections: dict) -> dict:
    warnings = [f"{group['label']} must use the same funding source when run together."
                for group in FUNDING_GROUPS
                if len({selections[stage].startswith("codex-dev/") for stage in group["stages"]}) > 1]
    if not selector_available() and any(model.startswith("codex-dev/") for model in selections.values()):
        warnings.append("Saved Codex choices are unavailable. Start the server with the Codex adaptor enabled or replace them with API models.")
    return {
        "codex_enabled": selector_available(), "funding_groups": FUNDING_GROUPS, "warnings": warnings,
        "enabled": True, "selections": selections, "models": models(),
        "stages": [{"id": stage, "label": STAGE_LABELS[stage], "model_ids": list(allowed_models(stage))} for stage in STAGE_FIELDS],
        "funding": "mixed" if any(model.startswith("codex-dev/") for model in selections.values()) and any(not model.startswith("codex-dev/") for model in selections.values()) else "codex_subscription" if all(model.startswith("codex-dev/") for model in selections.values()) else "api",
        "note": "Applies to new jobs in every project in this account. API choices use provider billing; Codex choices use the local subscription adaptor. Jobs cannot mix funding sources. Existing jobs and rendered editions keep their recorded models.",
    }


@router.get("/model-settings")
def get_model_settings(request: Request, user_id: str = Depends(get_current_user)):
    _require_development()
    try:
        return _payload(read_selections(request.app.state.projects_dir, user_id))
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.patch("/model-settings")
def patch_model_settings(body: ModelSettingsPatch, request: Request, user_id: str = Depends(get_current_user)):
    _require_development()
    try:
        return _payload(update_selections(request.app.state.projects_dir, user_id, body.selections))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

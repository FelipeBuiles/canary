"""Account-scoped local development preferences, read once per job request.

The immutable original-process gate cannot be enabled by a project dotenv file.
Files live alongside the account's projects, never inside one project. Writes
are locked and atomic so concurrent partial updates do not lose preferences.
"""
from __future__ import annotations

import fcntl
import json
import os
import tempfile
from pathlib import Path

from novel_to_comic.codex_dev import CodexRoutingError, process_setting, route_for, validate_local_runtime
from novel_to_comic.config import Config
from novel_to_comic.model_catalog import STAGE_FIELDS, default_selections, validate_selections


def model_settings_enabled() -> bool:
    if process_setting("CANARY_ENV") != "development":
        return False
    try:
        validate_local_runtime()
    except CodexRoutingError:
        return False
    return True


def _account_dir(root: Path, user_id: str) -> Path:
    if not user_id or Path(user_id).name != user_id or user_id in {".", ".."}:
        raise ValueError("Invalid account identifier")
    account = root / user_id
    if not account.resolve().is_relative_to(root.resolve()):
        raise ValueError("Invalid account directory")
    return account


def _read(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Unsupported account model settings version")
    return validate_selections(data["selections"])


def read_selections(root: Path, user_id: str) -> dict[str, str]:
    return {**default_selections(), **_read(_account_dir(root, user_id) / ".model-settings.json")}


def _require_available_routes(selections: dict[str, str]) -> None:
    for stage, model in selections.items():
        operation = "complete_page" if stage == "draw" else "image" if stage == "image" else "text"
        route = route_for(operation, model)
        if route is not None and not model.startswith("codex-dev/"):
            raise ValueError(f"{model} is overridden by the server's Codex route map; remove that override before selecting API models")


def update_selections(root: Path, user_id: str, changes: dict) -> dict[str, str]:
    validate_selections(changes)
    _require_available_routes(changes)
    account = _account_dir(root, user_id)
    account.mkdir(parents=True, exist_ok=True)
    path = account / ".model-settings.json"
    with (account / ".model-settings.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        selections = {**default_selections(), **_read(path), **changes}
        _require_available_routes(selections)
        fd, temporary = tempfile.mkstemp(prefix=".model-settings-", dir=account)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump({"version": 1, "selections": selections}, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return selections


def account_config(config: Config, root: Path, user_id: str) -> Config:
    """Snapshot account defaults and gated project choices without shared mutation."""
    enabled = model_settings_enabled()
    selections = read_selections(root, user_id) if enabled else default_selections()
    if enabled:
        selections.update(validate_selections(config.dev_model_selections))
    _require_available_routes(selections)
    return config.model_copy(deep=True, update={STAGE_FIELDS[k]: v for k, v in selections.items()})


def creation_config(overrides: dict, root: Path, user_id: str) -> Config:
    """Validate creation-only local model preferences before persisting a project."""
    if not isinstance(overrides, dict):
        raise ValueError("Project configuration must be an object")
    forbidden = set(STAGE_FIELDS.values()) | {"quality_preset", "fallback_image_model", "image_provider"}
    if forbidden.intersection(overrides):
        raise ValueError("Use dev_model_selections for local project model choices")
    if "dev_model_selections" in overrides:
        if not model_settings_enabled():
            raise ValueError("Project model choices require local development mode")
        validate_selections(overrides["dev_model_selections"])
    return account_config(Config(**overrides), root, user_id)

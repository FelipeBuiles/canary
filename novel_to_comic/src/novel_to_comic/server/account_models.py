"""Operator model defaults and account-scoped development preferences.

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

from novel_to_comic.codex_dev import CodexRoutingError, is_subscription_selector, process_setting, route_for, validate_local_runtime
from novel_to_comic.config import Config
from novel_to_comic.model_catalog import STAGE_FIELDS, allowed_models, default_selections, validate_selections

# Creation/import must not bypass the config edit API's trust boundary. These
# affect provider routing, credentials or billing, not a customer's book.
_SERVER_OWNED_CREATION_FIELDS = frozenset({
    "litellm_base_url", "litellm_api_key", "ai_bill_failed_requests",
    "mock_mode", "mock_model_base_url", "google_use_vertex_ai",
    "google_cloud_project", "google_cloud_location",
})


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
    account = root.resolve() / user_id
    if account.resolve() != account:
        raise ValueError("Invalid account directory")
    return account


def _read_raw(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict) or data.get("version") != 1:
        raise ValueError("Unsupported account model settings version")
    selections = data.get("selections")
    if not isinstance(selections, dict) or any(not isinstance(key, str) or not isinstance(value, str)
                                              for key, value in selections.items()):
        raise ValueError("Saved model selections must be a string mapping")
    return selections


def _supported_saved_selections(selections: dict[str, str]) -> dict[str, str]:
    """Use active saved choices without rewriting historical preferences.

    Retired API aliases must not prevent a project from opening. An explicit
    Codex subscription choice still fails closed if its route is no longer
    recognized, rather than silently switching that work to API billing.
    """
    supported = {}
    for stage, model in selections.items():
        if stage not in STAGE_FIELDS:
            continue
        if is_subscription_selector(model):
            validate_selections({stage: model})
        if model in allowed_models(stage):
            supported[stage] = model
    return supported


def _read(path: Path) -> dict[str, str]:
    return _supported_saved_selections(_read_raw(path))


def read_selections(root: Path, user_id: str) -> dict[str, str]:
    return {**read_global_selections(root), **_read(_account_dir(root, user_id) / ".model-settings.json")}


def read_global_selections(root: Path) -> dict[str, str]:
    """Read the operator defaults applied to new jobs for every account."""
    return {**default_selections(), **_read(root / ".operator-model-settings.json")}


def update_global_selections(root: Path, changes: dict) -> dict[str, str]:
    """Atomically update production-capable defaults without accepting Codex routes."""
    validate_selections(changes)
    if any(is_subscription_selector(model) for model in changes.values()):
        raise ValueError("Subscription models cannot be selected as operator defaults")
    root.mkdir(parents=True, exist_ok=True)
    path = root / ".operator-model-settings.json"
    with (root / ".operator-model-settings.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = _read_raw(path)
        selections = {**read_global_selections(root), **changes}
        _require_available_routes(selections)
        fd, temporary = tempfile.mkstemp(prefix=".operator-model-settings-", dir=root)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump({"version": 1, "selections": {**saved, **changes}}, output, indent=2)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return selections


def _require_available_routes(selections: dict[str, str]) -> None:
    for stage, model in selections.items():
        operation = "complete_page" if stage == "draw" else "image" if stage == "image" else "text"
        route = route_for(operation, model)
        if route is not None and not is_subscription_selector(model):
            raise ValueError(f"{model} is overridden by the server's Codex route map; remove that override before selecting API models")


def update_selections(root: Path, user_id: str, changes: dict) -> dict[str, str]:
    validate_selections(changes)
    _require_available_routes(changes)
    account = _account_dir(root, user_id)
    account.mkdir(parents=True, exist_ok=True)
    path = account / ".model-settings.json"
    with (account / ".model-settings.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        saved = _read_raw(path)
        selections = {**read_global_selections(root), **_supported_saved_selections(saved), **changes}
        _require_available_routes(selections)
        fd, temporary = tempfile.mkstemp(prefix=".model-settings-", dir=account)
        try:
            with os.fdopen(fd, "w") as output:
                json.dump({"version": 1, "selections": {**saved, **changes}}, output, indent=2)
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
    selections = read_global_selections(root)
    if enabled:
        selections.update(read_selections(root, user_id))
        selections.update(_supported_saved_selections(config.dev_model_selections))
    _require_available_routes(selections)
    return config.model_copy(deep=True, update={STAGE_FIELDS[k]: v for k, v in selections.items()})


def creation_config(overrides: dict, root: Path, user_id: str) -> Config:
    """Validate creation-only local model preferences before persisting a project."""
    if not isinstance(overrides, dict):
        raise ValueError("Project configuration must be an object")
    if _SERVER_OWNED_CREATION_FIELDS.intersection(overrides):
        raise ValueError("Operator configuration cannot be supplied in project overrides")
    forbidden = set(STAGE_FIELDS.values()) | {"quality_preset", "fallback_image_model", "image_provider"}
    if forbidden.intersection(overrides):
        raise ValueError("Use dev_model_selections for local project model choices")
    if "dev_model_selections" in overrides:
        if not model_settings_enabled():
            raise ValueError("Project model choices require local development mode")
        validate_selections(overrides["dev_model_selections"])
    return account_config(Config(**overrides), root, user_id)

"""Immutable, original-process authority for the opt-in local Codex adapter.

Imported by package initialization before project dotenv loading. Never consult
project configuration or the subsequently mutated environment for authority.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

Funding = Literal["api", "codex_subscription"]
_KEYS = (
    "CANARY_CODEX_DEV_ENABLED", "CANARY_ENV", "ENV", "FLY_APP_NAME",
    "FLY_MACHINE_ID", "RENDER", "RAILWAY_ENVIRONMENT", "K_SERVICE", "VERCEL",
    "CANARY_CODEX_DEV_TEXT_ROUTES", "CANARY_CODEX_DEV_IMAGE_ROUTES",
    "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR",
    "CANARY_CODEX_DEV_IMAGE_REASONING_MODEL", "CANARY_CODEX_DEV_MODELS",
)
_PROCESS = MappingProxyType({key: os.environ.get(key) for key in _KEYS})


class CodexRoutingError(ValueError):
    """A selected development route cannot safely execute."""


@dataclass(frozen=True, slots=True)
class CodexRoute:
    reasoning_model: str
    image_model: str | None = None


def process_setting(name: str) -> str | None:
    if name not in _PROCESS:
        raise KeyError(f"Unapproved Codex process setting: {name}")
    return _PROCESS[name]


def _model(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"gpt-[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise CodexRoutingError("Codex reasoning targets must be exact gpt-* model names")
    if value.startswith("gpt-image-"):
        raise CodexRoutingError("An image model is not a Codex reasoning target")
    return value


# Explicit local selectors are separate from API aliases. This allowlist is
# captured at import with the operator gate; project dotenv cannot extend it.
_DEFAULT_MODELS = (
    "gpt-6-astra", "gpt-6-sol", "gpt-6-luna",
    "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna",
    "gpt-5.5", "gpt-5.3-codex-spark",
)


def selectable_models() -> tuple[str, ...]:
    raw = _PROCESS["CANARY_CODEX_DEV_MODELS"]
    try:
        values = json.loads(raw) if raw else list(_DEFAULT_MODELS)
    except ValueError as exc:
        raise CodexRoutingError("CANARY_CODEX_DEV_MODELS must be a JSON list") from exc
    if not isinstance(values, list):
        raise CodexRoutingError("CANARY_CODEX_DEV_MODELS must be a JSON list")
    return tuple(dict.fromkeys(_model(value) for value in values))


def model_has_vision(model: str) -> bool:
    return model != "gpt-5.3-codex-spark"


def selector_available() -> bool:
    try:
        validate_startup()
        selectable_models()
        return enabled()
    except CodexRoutingError:
        return False


def _read_routes() -> tuple[dict[str, str], frozenset[str], str]:
    try:
        text = json.loads(_PROCESS["CANARY_CODEX_DEV_TEXT_ROUTES"] or "{}")
        images = json.loads(_PROCESS["CANARY_CODEX_DEV_IMAGE_ROUTES"] or "[]")
    except (TypeError, ValueError) as exc:
        raise CodexRoutingError("Codex route settings must be valid JSON") from exc
    if not isinstance(text, dict) or not all(isinstance(k, str) and k.strip() == k and k for k in text):
        raise CodexRoutingError("Codex text routes must be an alias-to-model JSON object")
    if not isinstance(images, list) or not all(isinstance(k, str) and k.strip() == k and k for k in images):
        raise CodexRoutingError("Codex image routes must be a JSON list of aliases")
    return {k: _model(v) for k, v in text.items()}, frozenset(images), _model(
        _PROCESS["CANARY_CODEX_DEV_IMAGE_REASONING_MODEL"] or "gpt-5.5"
    )


try:
    _text, _IMAGES, _IMAGE_REASONING = _read_routes()
    _TEXT = MappingProxyType(_text)
    _SETTINGS_ERROR: str | None = None
except CodexRoutingError as exc:
    _TEXT = MappingProxyType({})
    _IMAGES = frozenset()
    _IMAGE_REASONING = "gpt-5.5"
    _SETTINGS_ERROR = str(exc)


def enabled() -> bool:
    return _PROCESS["CANARY_CODEX_DEV_ENABLED"] == "1"


def validate_local_runtime() -> None:
    """Veto hosted/explicit nondevelopment use, including standalone probes."""
    if (
        _PROCESS["CANARY_ENV"] not in {None, "", "development"}
        or (_PROCESS["ENV"] or "").lower() in {"prod", "production"}
    ):
        raise CodexRoutingError("Codex runtime is restricted to local development")
    if any(_PROCESS[key] for key in ("FLY_APP_NAME", "FLY_MACHINE_ID", "RENDER", "RAILWAY_ENVIRONMENT", "K_SERVICE", "VERCEL")):
        raise CodexRoutingError("Codex development routing is forbidden on hosted platforms")


def validate_startup(host: str | None = None) -> None:
    if not enabled():
        return
    validate_local_runtime()
    if _PROCESS["CANARY_ENV"] != "development":
        raise CodexRoutingError("Codex requires original-process CANARY_ENV=development")
    if _SETTINGS_ERROR:
        raise CodexRoutingError(_SETTINGS_ERROR)
    selectable_models()
    if host is not None and not is_loopback(host):
        raise CodexRoutingError("Codex development serving requires a loopback bind address")


def is_loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def route_for(kind: str, model: str) -> CodexRoute | None:
    if kind not in {"text", "image", "complete_page"}:
        raise CodexRoutingError(f"Unsupported operation kind: {kind}")
    if _SETTINGS_ERROR:
        raise CodexRoutingError(_SETTINGS_ERROR)
    explicit_kind, separator, target = model.removeprefix("codex-dev/").partition("/")
    explicit = model.startswith("codex-dev/") and separator and explicit_kind in {"text", "image"}
    if explicit:
        if target not in selectable_models():
            raise CodexRoutingError("Codex model is absent from the original-process model allowlist")
        if (kind == "text") != (explicit_kind == "text"):
            raise CodexRoutingError("Selected Codex model does not support this operation kind")
        if explicit_kind == "image" and not model_has_vision(target):
            raise CodexRoutingError("Selected Codex reasoning model does not support images")
        if not enabled():
            raise CodexRoutingError("Selected Codex route requires CANARY_CODEX_DEV_ENABLED=1")
        validate_startup()
        return CodexRoute(target) if kind == "text" else CodexRoute(target, "gpt-image-2")
    selected = model in (_TEXT if kind == "text" else _IMAGES)
    if not selected and (model in _TEXT or model in _IMAGES):
        raise CodexRoutingError("Selected Codex alias does not support this operation kind")
    if not selected and not model.startswith("codex-dev/"):
        return None
    if not enabled():
        raise CodexRoutingError("Selected Codex route requires CANARY_CODEX_DEV_ENABLED=1")
    validate_startup()
    if not selected:
        raise CodexRoutingError("Explicit Codex selection is absent from the process route map")
    if kind == "complete_page":
        # A page profile is chosen by the Draw selection itself; an alias route
        # would price a Codex page while Draw still selects the API profile.
        raise CodexRoutingError(
            "Complete-page Codex routing requires an explicit codex-dev/image/<model> Draw selection"
        )
    return CodexRoute(_TEXT[model]) if kind == "text" else CodexRoute(_IMAGE_REASONING, "gpt-image-2")


def classify_operations(operations: Sequence[tuple[str, str]]) -> Funding:
    """Validate routes and summarize whether the work contains API spend.

    This is an estimate label, not an execution lock. Codex is a local transport;
    it can be mixed with API calls in any job. Each call owns its usage and only
    API calls settle credits. Visit every route so a disabled/invalid Codex
    selection still fails before work starts.
    """
    routes = [route_for(kind, model) for kind, model in operations]
    return "codex_subscription" if routes and all(routes) else "api"

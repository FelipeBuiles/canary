"""Immutable, original-process authority for the opt-in local Codex adapter.

Imported by package initialization before project dotenv loading. Never consult
project configuration or the subsequently mutated environment for authority.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

Funding = Literal["api", "codex_subscription"]
_KEYS = (
    "CANARY_CODEX_DEV_ENABLED", "CANARY_ENV", "ENV", "FLY_APP_NAME",
    "FLY_MACHINE_ID", "RENDER", "RAILWAY_ENVIRONMENT", "K_SERVICE", "VERCEL",
    "CANARY_CODEX_DEV_TEXT_ROUTES", "CANARY_CODEX_DEV_IMAGE_ROUTES",
    "HOME", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR",
    "CANARY_CODEX_DEV_IMAGE_REASONING_MODEL",
)
_PROCESS = MappingProxyType({key: os.environ.get(key) for key in _KEYS})
_FUNDING: ContextVar[Funding | None] = ContextVar("codex_admitted_funding", default=None)


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
    if kind == "complete_page" and model != "image-balanced":
        raise CodexRoutingError("Complete-page development routing requires the original-process image-balanced selection")
    return CodexRoute(_TEXT[model]) if kind == "text" else CodexRoute(_IMAGE_REASONING, "gpt-image-2")


def classify_operations(operations: Sequence[tuple[str, str]]) -> Funding:
    fundings = {"codex_subscription" if route_for(kind, model) else "api" for kind, model in operations}
    if len(fundings) > 1:
        raise CodexRoutingError("A job cannot mix API-funded and Codex-subscription operations")
    return "codex_subscription" if "codex_subscription" in fundings else "api"


@contextmanager
def funding_scope(funding: Funding) -> Iterator[None]:
    if funding not in {"api", "codex_subscription"}:
        raise CodexRoutingError("Unknown admitted funding")
    previous = _FUNDING.get()
    if previous is not None and previous != funding:
        raise CodexRoutingError("Nested job funding disagrees with admitted funding")
    token = _FUNDING.set(funding)
    try:
        yield
    finally:
        _FUNDING.reset(token)


def assert_request_funding(kind: str, model: str, *, require_admission: bool = False) -> None:
    actual = classify_operations(((kind, model),))
    admitted = _FUNDING.get()
    if require_admission and admitted is None and actual == "codex_subscription":
        raise CodexRoutingError("A selected Codex request in a job requires admitted funding")
    if admitted is not None and admitted != actual:
        raise CodexRoutingError("Request funding disagrees with the admitted job")


def require_same_text_target(*models: str) -> None:
    classify_operations(tuple(("text", model) for model in models))
    targets = {route.reasoning_model for model in models if (route := route_for("text", model))}
    if len(targets) > 1:
        raise CodexRoutingError("Automatic escalation cannot switch Codex reasoning models")

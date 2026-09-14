"""Shared AI client errors."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from novel_to_comic.usage import UsageRecord


class AIRefusalError(RuntimeError):
    """Raised when a gateway or provider reports a safety/policy refusal."""

    def __init__(
        self,
        message: str,
        *,
        response_data: dict[str, Any] | None = None,
        response_headers: httpx.Headers | None = None,
        response: httpx.Response | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.response_data = response_data
        self.response_headers = response_headers
        self.response = response
        self.diagnostics = diagnostics or {}


class AITransportError(ValueError):
    """A provider/gateway transport failure with safe diagnostic metadata."""

    def __init__(
        self,
        message: str,
        *,
        phase: str,
        response: httpx.Response | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.phase = phase
        self.response = response
        self.diagnostics = diagnostics or {}


class AIEmptyResponseError(AITransportError):
    """A completed text request returned no answer and no explicit provider error."""

    usage: UsageRecord | None = None

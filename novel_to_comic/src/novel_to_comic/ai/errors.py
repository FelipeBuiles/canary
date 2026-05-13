"""Shared AI client errors."""

from __future__ import annotations

from typing import Any

import httpx


class AIRefusalError(RuntimeError):
    """Raised when a gateway or provider reports a safety/policy refusal."""

    def __init__(
        self,
        message: str,
        *,
        response_data: dict[str, Any] | None = None,
        response_headers: httpx.Headers | None = None,
        response: httpx.Response | None = None,
    ) -> None:
        super().__init__(message)
        self.response_data = response_data
        self.response_headers = response_headers
        self.response = response

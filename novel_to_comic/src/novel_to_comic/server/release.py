"""Public, non-sensitive release identity for support and deployment checks."""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError, version


def application_version() -> str:
    """Return the installed package version without requiring build metadata."""
    try:
        return version("novel-to-comic")
    except PackageNotFoundError:
        return "0.1.0"


def release_identity() -> dict[str, str]:
    """Return the immutable build identifiers exposed by ``/api/version``."""
    return {
        "application_version": application_version(),
        "git_sha": os.environ.get("CANARY_VERSION", "unknown").strip() or "unknown",
        "build_timestamp": (
            os.environ.get("CANARY_BUILD_TIMESTAMP", "unknown").strip() or "unknown"
        ),
    }

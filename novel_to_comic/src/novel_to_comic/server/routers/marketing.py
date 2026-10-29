"""Local backoffice adapter for the marketing workspace's canonical TypeScript rules."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response

from ..deployment_status import require_ops_token

router = APIRouter(dependencies=[Depends(require_ops_token)])
CANARY_ROOT = Path(__file__).resolve().parents[5]


def require_local(request: Request) -> None:
    from novel_to_comic.codex_dev import is_loopback

    if (
        request.client is None
        or not is_loopback(request.client.host)
        or not is_loopback(request.url.hostname or "")
        or any(
            name in request.headers
            for name in (
                "forwarded",
                "x-forwarded-for",
                "x-forwarded-host",
                "x-forwarded-proto",
            )
        )
    ):
        raise HTTPException(403, "Marketing requires a direct loopback request")


def run_desk(command: Literal["snapshot", "transition"], payload: object) -> dict:
    root = CANARY_ROOT / "marketing"
    loader = root / "node_modules/tsx/dist/cli.mjs"
    node = shutil.which("node")
    if node is None or not loader.is_file():
        raise HTTPException(
            503,
            "Marketing tooling is unavailable. Install Node and run npm ci in marketing/.",
        )
    try:
        with (root / ".desk.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            result = subprocess.run(
                [node, str(loader), str(root / "scripts/desk.ts"), command],
                input=json.dumps(payload),
                capture_output=True,
                text=True,
                timeout=30,
                cwd=root,
                env={**os.environ, "CANARY_ROOT": str(CANARY_ROOT)},
                check=True,
            )
        envelope = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise HTTPException(
            503,
            "Marketing request could not be confirmed. Refresh the desk before trying again.",
        ) from exc
    if not isinstance(envelope, dict):
        raise HTTPException(503, "Invalid marketing tooling response")
    if envelope.get("ok") is True and isinstance(envelope.get("snapshot"), dict):
        return envelope["snapshot"]
    status = envelope.get("status")
    detail = envelope.get("detail")
    raise HTTPException(
        status if status in (400, 404, 409, 503) else 503,
        detail if isinstance(detail, str) else "Invalid marketing tooling response",
    )


@router.get("/snapshot", dependencies=[Depends(require_local)])
def snapshot(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return run_desk("snapshot", None)


async def validate_transition(request: Request) -> None:
    if (
        request.headers.get("content-type", "").split(";")[0].strip().lower()
        != "application/json"
    ):
        raise HTTPException(415, "application/json required")
    if len(await request.body()) > 64 * 1024:
        raise HTTPException(413, "Marketing request exceeds 64 KiB")


@router.post(
    "/transition",
    dependencies=[Depends(require_local), Depends(validate_transition)],
    openapi_extra={
        "x-canary-action": {"spends": False, "dispatches": False, "replay": False}
    },
)
def transition(payload: dict, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return run_desk("transition", payload)

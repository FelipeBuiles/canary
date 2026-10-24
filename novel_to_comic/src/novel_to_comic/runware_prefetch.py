"""Store Draw's references on Runware as soon as Cast is approved.

Runware takes references by uploaded media UUID, and the first pages of a Draw
run would otherwise wait for those uploads (seconds to tens of seconds each).
The approved Cast images, location plates and props are fixed at approval, and
Adapt and Plan run for minutes before Draw, so the server sends them to the
gateway's Runware route then, flagged upload-only: the gateway stores them and
keeps their UUIDs in its media cache, and no image task runs. Uploads are free
and content-addressed, so a repeat or an unused upload costs nothing.

Best effort only: it runs in the background, never spends credits, and any
failure leaves Draw to upload on demand as before. Pages that combine more
references into sheets upload those sheets when they are drawn.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import httpx

from novel_to_comic.config import Config
from novel_to_comic.image_models import GATEWAY_IMAGE_SUNBURST_RUNWARE, runware_first_enabled

logger = logging.getLogger(__name__)

#: Upload-only flag the Runware gateway handler recognises.
PREFETCH_PARAM = "canary_runware_prefetch"
TIMEOUT_S = 600.0


def reference_paths(project_dir: Path) -> list[Path]:
    """Each distinct approved reference file Draw may send, in a stable order."""
    from novel_to_comic.stages.s5_plan import approved_reference_files

    paths = {Path(item.path) for item in approved_reference_files(project_dir).values()}
    return sorted(path for path in paths if path.is_file())


def prefetch(config: Config, project_dir: Path) -> int:
    """Send the approved references to the gateway, upload-only. Returns the count."""
    if config.mock_mode or not runware_first_enabled():
        return 0
    paths = reference_paths(project_dir)
    if not paths:
        return 0
    headers = {"Authorization": f"Bearer {config.litellm_api_key}"} if config.litellm_api_key else {}
    files = [("image", (path.name, path.read_bytes(), "image/png")) for path in paths]
    with httpx.Client(timeout=TIMEOUT_S) as http:
        response = http.post(
            f"{config.litellm_base_url.rstrip('/')}/v1/images/edits", headers=headers, files=files,
            data={"model": GATEWAY_IMAGE_SUNBURST_RUNWARE, "prompt": "Store references", "n": "1",
                  "response_format": "b64_json", PREFETCH_PARAM: "1"},
        )
    response.raise_for_status()
    return len(paths)


def start(config: Config, project_dir: Path) -> None:
    """Prefetch in a background thread; never raises."""
    if config.mock_mode or not runware_first_enabled():
        return

    def run() -> None:
        try:
            count = prefetch(config, project_dir)
        except Exception as exc:  # noqa: BLE001 - Draw uploads on demand instead.
            logger.warning("Runware reference prefetch failed project=%s error=%s",
                           project_dir.name, type(exc).__name__)
            return
        logger.info("Runware references stored ahead of Draw project=%s count=%d", project_dir.name, count)

    threading.Thread(target=run, name="runware-prefetch", daemon=True).start()

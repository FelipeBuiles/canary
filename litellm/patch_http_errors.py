"""Patch the pinned gateway's multipart error masking without reading uploads.

LiteLLM 1.83.14 accesses Request.content while wrapping HTTP errors. Multipart
requests are streams, so that access raises RequestNotRead and hides the real
provider status/body. The sanitized exception does not need a request body.
Apply at image build time, failing closed if the pinned source changes.
"""
from importlib.util import find_spec
from pathlib import Path
import sys


def patch_source(source: str) -> str:
    old = "content=original_error.request.content,"
    new = 'content=b"",  # Canary: never consume an upload while masking an error.'
    if new in source:
        return source
    if source.count(old) != 1:
        raise RuntimeError("LiteLLM HTTP error handler changed; review the multipart patch")
    return source.replace(old, new)


if __name__ == "__main__":
    spec = find_spec("litellm")
    assert spec is not None and spec.origin is not None
    # The upstream image has both an /app checkout and a site-packages copy.
    # Patch both so the entrypoint's working directory cannot select the bug.
    relative = Path("litellm/llms/custom_httpx/http_handler.py")
    targets = {Path(entry) / relative for entry in sys.path}
    targets.add(Path(spec.origin).parent / "llms/custom_httpx/http_handler.py")
    for target in targets:
        if target.is_file():
            target.write_text(patch_source(target.read_text()))

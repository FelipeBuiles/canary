"""Keep upload bodies out of LiteLLM 1.101.0's sanitized HTTP exceptions.

Upstream now catches RequestNotRead, but still copies buffered request bodies.
The sanitized error needs the provider status/body, never the submitted image.
Fail closed on unknown source layouts or missing patch targets.
"""
from importlib.util import find_spec
from pathlib import Path
import sys


MARKER = 'content=b"",  # Canary: never consume an upload while masking an error.'
REQUEST_READ = '''        try:
            request_content = original_error.request.content
        except httpx.RequestNotRead:
            request_content = b""

'''


def patch_source(source: str) -> str:
    if MARKER in source:
        return source
    old = 'headers=original_error.request.headers,\n            content=request_content,'
    if source.count(REQUEST_READ) != 1 or source.count(old) != 1:
        raise RuntimeError("LiteLLM HTTP error handler changed; review the multipart patch")
    return source.replace(REQUEST_READ, "").replace(old, old.replace("content=request_content,", MARKER))


def main() -> None:
    spec = find_spec("litellm")
    if spec is None or spec.origin is None:
        raise RuntimeError("LiteLLM package could not be located")
    relative = Path("litellm/llms/custom_httpx/http_handler.py")
    targets = {Path(entry) / relative for entry in sys.path}
    targets.add(Path(spec.origin).parent / "llms/custom_httpx/http_handler.py")
    targets = {target.resolve() for target in targets if target.is_file()}
    if not targets:
        raise RuntimeError(f"No LiteLLM HTTP patch targets beside {spec.origin}")
    for target in sorted(targets):
        target.write_text(patch_source(target.read_text()))
        print(f"Verified HTTP error patch: {target}")


if __name__ == "__main__":
    main()

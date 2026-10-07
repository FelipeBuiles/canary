"""Keep upload bodies out of LiteLLM 1.101.0's sanitized HTTP exceptions.

Upstream now catches RequestNotRead, but still copies buffered request bodies.
The sanitized error needs the provider status/body, never the submitted image.
Fail closed on unknown source layouts or missing patch targets.
"""
from importlib.util import find_spec
from pathlib import Path
import sys


MARKER = 'content=b"",  # Canary: never consume an upload while masking an error.'
METRICS_MIDDLEWARE_MARKER = "app.add_middleware(PostHogMetricsMiddleware)"
PREVIEW_MIDDLEWARE_MARKER = "app.add_middleware(ImagePreviewMiddleware)"
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


def patch_proxy_source(source: str) -> str:
    if METRICS_MIDDLEWARE_MARKER in source and PREVIEW_MIDDLEWARE_MARKER in source:
        return source
    previews = (
        "from litellm_handlers.image_previews import ImagePreviewMiddleware\n\n"
        f"{PREVIEW_MIDDLEWARE_MARKER}\n\n"
    )
    if METRICS_MIDDLEWARE_MARKER in source:
        return source.replace(METRICS_MIDDLEWARE_MARKER, previews + METRICS_MIDDLEWARE_MARKER)
    anchor = "app.add_middleware(\n    CORSMiddleware,"
    if source.count(anchor) != 1:
        raise RuntimeError("LiteLLM middleware layout changed; review the metrics patch")
    metrics = (
        "from canary_metrics import PostHogMetricsMiddleware\n\n"
        f"{METRICS_MIDDLEWARE_MARKER}\n\n"
    )
    return source.replace(anchor, previews + metrics + anchor)


def main() -> None:
    spec = find_spec("litellm")
    if spec is None or spec.origin is None:
        raise RuntimeError("LiteLLM package could not be located")
    package = Path(spec.origin).parent
    relative = Path("litellm/llms/custom_httpx/http_handler.py")
    targets = {Path(entry) / relative for entry in sys.path}
    targets.add(package / "llms/custom_httpx/http_handler.py")
    targets = {target.resolve() for target in targets if target.is_file()}
    if not targets:
        raise RuntimeError(f"No LiteLLM HTTP patch targets beside {spec.origin}")
    for target in sorted(targets):
        target.write_text(patch_source(target.read_text()))
        print(f"Verified HTTP error patch: {target}")

    proxy_server = package / "proxy/proxy_server.py"
    if not proxy_server.is_file():
        raise RuntimeError(f"LiteLLM proxy server could not be located beside {spec.origin}")
    proxy_server.write_text(patch_proxy_source(proxy_server.read_text()))
    print(f"Verified PostHog metrics middleware patch: {proxy_server}")


if __name__ == "__main__":
    main()

"""Downloads own the verified open file, including cancellation before iteration."""

from starlette.background import BackgroundTask
from starlette.responses import StreamingResponse


def download_response(stream, *, size: int, name: str, media_type: str):
    def chunks():
        try:
            while data := stream.read(64 * 1024):
                yield data
        finally:
            stream.close()

    return StreamingResponse(
        chunks(),
        media_type=media_type,
        background=BackgroundTask(stream.close),
        headers={
            "Content-Length": str(size),
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'attachment; filename="{name}"',
        },
    )

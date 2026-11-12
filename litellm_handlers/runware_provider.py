"""LiteLLM custom provider for GPT Image 2.5 through Runware's REST API.

Behaviour verified against the live API on 2026-10-23:

- References go by media-storage UUID. Inline data URIs take ~50 s to ingest
  for a five-reference page; an uploaded UUID adds <1 s. Uploads are free and
  content-addressed (identical bytes return the same UUID), so the cache below
  is an optimisation, never an identity.
- A reference UUID Runware no longer has is rejected synchronously with
  ``failedToTransferImage`` before anything runs, so re-uploading and
  submitting once more cannot double-charge.
- Failed tasks are not billed. An explicit Runware error is a definite outcome.
- ``getResponse`` answers "processing" for any UUID, even unknown ones, so it
  is never used. ``getTaskDetails`` is authoritative but eventually
  consistent: ``taskNotFound`` for ~10 s after submission. It returns cost and
  ``imageUUID`` but not the image bytes; the image is served at a public URL.

The handler submits each task exactly once. When the answer is lost after the
request may have been sent, it recovers the task by its ``taskUUID`` instead of
resubmitting; only an unresolved recovery surfaces as an unknown outcome.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

import httpx
try:
    from litellm.llms.custom_llm import CustomLLM, CustomLLMError
    from litellm.types.utils import ImageObject, ImageResponse
except ModuleNotFoundError:
    # Keep the pure helpers importable in the application test environment,
    # where the isolated LiteLLM proxy dependency is absent.
    class CustomLLM:
        pass

    class CustomLLMError(Exception):
        def __init__(self, status_code: int, message: str):
            self.status_code = status_code
            self.message = message
            super().__init__(message)

    class ImageObject:
        def __init__(self, **kwargs: Any):
            self.__dict__.update(kwargs)

    class ImageResponse:
        pass


RUNWARE_API = "https://api.runware.ai/v1"
RUNWARE_IMAGE_URL = "https://im.runware.ai/image/ii/{image_uuid}.png"
#: Canary model names and their Runware AIR identifiers.
SUPPORTED_MODELS = {
    "gpt-image-2.5-sunburst": "openai:gpt-image@2.5-sunburst",
    "gpt-image-2.5-flare": "openai:gpt-image@2.5-flare",
    # Listed in Runware's catalog (modelSearch, 2026-11-10); Labs routes only.
    "gpt-image-2.6-sunburst": "openai:gpt-image@2.6-sunburst",
    "gpt-image-2.6-flare": "openai:gpt-image@2.6-flare",
    # MiniMax H3 Image (Runware docs, 2026-11-10); Labs routes only.
    "minimax-h3-image": "minimax:h3@image",
    "minimax-h3-image-highspeed": "minimax:h3@image-highspeed",
}
#: MiniMax H3 models: no quality, background or moderation settings. Runware's
#: ``safety.checkContent`` is the only content control and stays off.
MINIMAX_MODELS = frozenset({"minimax-h3-image", "minimax-h3-image-highspeed"})
#: MiniMax H3 accepts 468-7745 px per side, 0.66-20 MP and 1:3 to 3:1.
MINIMAX_MIN_SIDE, MINIMAX_MAX_SIDE = 468, 7745
MINIMAX_MIN_PIXELS, MINIMAX_MAX_PIXELS = 660_000, 20_000_000
SUBMIT_TIMEOUT_S = 300.0
CONNECT_TIMEOUT_S = 10.0
UPLOAD_TIMEOUT_S = 120.0
#: How long recovery polls ``getTaskDetails`` after a lost answer.
RECOVERY_TIMEOUT_S = 300.0
#: ``taskNotFound`` is expected this long after submission (observed ~10 s).
NOT_FOUND_GRACE_S = 60.0
RECOVERY_POLL_S = (2.0, 5.0)
UPLOAD_ATTEMPTS = 3
MEDIA_CACHE_SIZE = 1024
#: Balance lookups ride on Runware traffic, at most this often (a 402 forces one).
BALANCE_REFRESH_S = 300.0
BALANCE_TIMEOUT_S = 10.0
#: Log an error when the balance drops below this many USD.
DEFAULT_BALANCE_ALERT_USD = 25.0
#: Upload-only requests (references stored ahead of Draw) and their parallelism.
PREFETCH_PARAM = "canary_runware_prefetch"
PREFETCH_CONCURRENCY = 4
# Controls the frozen manifest may carry; anything else is rejected, never
# forwarded or dropped silently.
_ALLOWED_CONTROLS = frozenset({"quality", "output_format", "n", "background"})
_MINIMAX_CONTROLS = frozenset({"output_format", "n"})
# Same provider policy as the direct OpenAI route: "low" is the least
# restrictive moderation tier GPT Image offers.
MODERATION = "low"
_STALE_REFERENCE_CODE = "failedToTransferImage"

logger = logging.getLogger(__name__)
_URI_RE = re.compile(r"(?:data:[^\s,]+,|https?://)\S+", re.IGNORECASE)


class RunwareImageError(CustomLLMError):
    """A redacted, phase-tagged provider error.

    Phases the application relies on:
    - ``request_validation``: the request never left the gateway.
    - ``upload``: a reference could not be stored; no task was submitted.
    - ``submit_connect``: no connection was made; Runware cannot have the task.
    - ``submit``: Runware answered the task with an error. Failed tasks are not
      billed; ``code`` carries Runware's error code.
    - ``unknown_outcome``: the answer was lost and recovery could not establish
      whether the task ran. It may have been charged.
    - ``result``: the task completed without a usable image.
    """

    def __init__(
        self,
        *,
        status_code: int,
        phase: str,
        model: str,
        upstream_status: int | None = None,
        code: str | None = None,
        task_uuid: str | None = None,
        detail: str | None = None,
    ) -> None:
        self.phase = phase
        self.model = model
        self.upstream_status = upstream_status
        self.code = code
        self.task_uuid = task_uuid
        self.detail = detail
        upstream = f"; upstream_status={upstream_status}" if upstream_status is not None else ""
        error_code = f"; code={code}" if code else ""
        task = f"; task_uuid={task_uuid}" if task_uuid else ""
        suffix = f"; detail={detail}" if detail else ""
        super().__init__(
            status_code=status_code,
            message=f"Runware image {phase} failed for {model}{upstream}{error_code}{task}{suffix}",
        )


class _MediaCache:
    """Process-local map from reference sha256 to Runware media UUID.

    Concurrent pages that share a Cast reference wait on one upload.
    """

    def __init__(self, size: int = MEDIA_CACHE_SIZE) -> None:
        self._size = size
        self._ids: OrderedDict[str, str] = OrderedDict()
        self._pending: dict[str, asyncio.Future[str]] = {}

    def get(self, digest: str) -> str | None:
        media_uuid = self._ids.get(digest)
        if media_uuid is not None:
            self._ids.move_to_end(digest)
        return media_uuid

    def put(self, digest: str, media_uuid: str) -> None:
        self._ids[digest] = media_uuid
        self._ids.move_to_end(digest)
        while len(self._ids) > self._size:
            self._ids.popitem(last=False)

    def evict(self, media_uuid: str) -> None:
        for digest in [d for d, m in self._ids.items() if m == media_uuid]:
            del self._ids[digest]

    def clear(self) -> None:
        self._ids.clear()
        self._pending.clear()

    async def resolve(self, data: bytes, upload) -> str:
        digest = hashlib.sha256(data).hexdigest()
        cached = self.get(digest)
        if cached is not None:
            return cached
        pending = self._pending.get(digest)
        if pending is not None:
            return await asyncio.shield(pending)
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending[digest] = future
        try:
            media_uuid = await upload(data)
        except asyncio.CancelledError:
            future.cancel()
            raise
        except BaseException as exc:
            future.set_exception(exc)
            future.exception()  # Waiters re-raise; don't log it as unretrieved.
            raise
        finally:
            self._pending.pop(digest, None)
        self.put(digest, media_uuid)
        future.set_result(media_uuid)
        return media_uuid


MEDIA_CACHE = _MediaCache()


def _record_metric(kind: str, name: str, value: float) -> None:
    try:
        from canary_metrics import record
    except ImportError:  # Outside the gateway image (tests, tooling).
        return
    record(kind, name, value)


def balance_alert_usd() -> float:
    raw = os.environ.get("RUNWARE_BALANCE_ALERT_USD", "").strip()
    try:
        value = float(raw) if raw else DEFAULT_BALANCE_ALERT_USD
    except ValueError:
        return DEFAULT_BALANCE_ALERT_USD
    return value if math.isfinite(value) and value >= 0 else DEFAULT_BALANCE_ALERT_USD


class _BalanceMonitor:
    """Watches the prepaid Runware balance (the startup grant).

    A spent balance answers every task with 402, which Canary survives by
    falling back to OpenAI; this makes the run-down visible before that. Each
    lookup is free and runs in the background, never delaying an image.
    Reports the ``runware.balance_usd`` gauge and logs an error once per
    crossing below ``RUNWARE_BALANCE_ALERT_USD``.
    """

    def __init__(self, *, refresh_s: float = BALANCE_REFRESH_S, clock=time.monotonic) -> None:
        self._refresh_s = refresh_s
        self._clock = clock
        self._next_at = 0.0
        self._low = False
        self._task: asyncio.Task[None] | None = None
        self.balance_usd: float | None = None

    def observe(self, headers: dict[str, str], *, force: bool = False) -> None:
        now = self._clock()
        if self._task is not None and not self._task.done():
            return
        if not force and now < self._next_at:
            return
        self._next_at = now + self._refresh_s
        self._task = asyncio.get_running_loop().create_task(self.refresh(headers))

    async def refresh(self, headers: dict[str, str]) -> float | None:
        try:
            async with httpx.AsyncClient(timeout=BALANCE_TIMEOUT_S) as http:
                response = await http.post(RUNWARE_API, headers=headers, json=[{
                    "taskType": "accountManagement", "taskUUID": str(uuid.uuid4()), "operation": "getDetails",
                }])
            entry = _first(_json(response), "data")
            balance = float(entry["balance"]) if isinstance(entry, dict) else math.nan
        except Exception as exc:  # noqa: BLE001 - monitoring never affects images.
            logger.warning("Runware balance lookup failed error=%s", type(exc).__name__)
            return None
        if not math.isfinite(balance):
            logger.warning("Runware balance lookup returned no balance status=%s", response.status_code)
            return None
        self.balance_usd = balance
        _record_metric("gauge", "runware.balance_usd", balance)
        threshold = balance_alert_usd()
        if balance < threshold and not self._low:
            self._low = True
            logger.error("Runware balance low balance_usd=%.2f threshold_usd=%.2f; when it runs out, "
                         "Runware-first images fall back to OpenAI", balance, threshold)
        elif balance >= threshold and self._low:
            self._low = False
            logger.info("Runware balance restored balance_usd=%.2f threshold_usd=%.2f", balance, threshold)
        return balance


BALANCE = _BalanceMonitor()


class RunwareImageLLM(CustomLLM):
    """Custom LiteLLM provider for GPT Image 2.5 generations and edits on Runware."""

    def image_edit(
        self,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None = None,
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return asyncio.run(self._generate_async(
            model=model, image=image, prompt=prompt, model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
        ))

    async def aimage_edit(
        self,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None = None,
        api_base: str | None = None,  # noqa: ARG002
        optional_params: dict[str, Any] | None = None,
        logging_obj: Any | None = None,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return await self._generate_async(
            model=model, image=image, prompt=prompt, model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
        )

    async def aimage_generation(
        self,
        model: str,
        prompt: str,
        api_key: str | None,
        api_base: str | None,  # noqa: ARG002
        model_response: ImageResponse,
        optional_params: dict[str, Any],
        logging_obj: Any,  # noqa: ARG002
        timeout: float | httpx.Timeout | None = None,
        client: Any | None = None,  # noqa: ARG002
        **kwargs: Any,  # noqa: ARG002
    ) -> ImageResponse:
        return await self._generate_async(
            model=model, image=[], prompt=prompt, model_response=model_response,
            api_key=api_key, optional_params=optional_params or {}, timeout=timeout,
        )

    async def _generate_async(
        self,
        *,
        model: str,
        image: list[Any],
        prompt: str | None,
        model_response: ImageResponse,
        api_key: str | None,
        optional_params: dict[str, Any],
        timeout: float | httpx.Timeout | None,
    ) -> ImageResponse:
        upstream_model = upstream_model_name(model)
        if str(optional_params.get(PREFETCH_PARAM) or "").strip().lower() in {"1", "true"}:
            return await self._prefetch(model=upstream_model, image=image, model_response=model_response,
                                        api_key=api_key)
        task = inference_task(upstream_model, prompt or "", optional_params)
        references = [reference_bytes(item, index, model=upstream_model) for index, item in enumerate(image)]
        read_timeout = float(timeout) if isinstance(timeout, (int, float)) else SUBMIT_TIMEOUT_S
        headers = _headers(api_key)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(read_timeout, connect=CONNECT_TIMEOUT_S)) as http:
                result = await generate(http, headers, task, references, model=upstream_model)
                image_bytes = await _image_bytes(http, result, model=upstream_model, task_uuid=task["taskUUID"])
        except RunwareImageError as exc:
            if exc.upstream_status == 402:
                _record_metric("count", "runware.insufficient_credits", 1)
                BALANCE.observe(headers, force=True)
            raise
        BALANCE.observe(headers)
        cost = _cost(result)
        model_response.created = int(time.time())
        model_response.data = [ImageObject(b64_json=base64.b64encode(image_bytes).decode("ascii"))]
        model_response._hidden_params["model"] = upstream_model
        model_response._hidden_params["custom_llm_provider"] = "runware"
        model_response._hidden_params["provider_request_id"] = task["taskUUID"]
        model_response._hidden_params["response_cost"] = cost
        # Runware returns no token usage; it reports the charged amount, which
        # Canary settles as the actual provider cost.
        model_response.provider_request_id = task["taskUUID"]
        model_response.model = f"runware/{upstream_model}"
        if cost is not None:
            model_response.provider_cost_usd = cost
            model_response.provider_cost_source = "runware_cost"
        return model_response


    async def _prefetch(self, *, model: str, image: list[Any], model_response: ImageResponse,
                        api_key: str | None) -> ImageResponse:
        """Store references in media storage without running a task.

        Uploads are free and content-addressed, so this charges nothing; later
        pages find the UUIDs in the cache. The response carries no image.
        """
        references = [reference_bytes(item, index, model=model) for index, item in enumerate(image)]
        headers = _headers(api_key)
        gate = asyncio.Semaphore(PREFETCH_CONCURRENCY)

        async def store(http: httpx.AsyncClient, data: bytes) -> str:
            async with gate:
                return await _upload(http, headers, data, model=model)

        started = time.monotonic()
        async with httpx.AsyncClient(timeout=httpx.Timeout(UPLOAD_TIMEOUT_S, connect=CONNECT_TIMEOUT_S)) as http:
            await asyncio.gather(*(MEDIA_CACHE.resolve(data, lambda d: store(http, d)) for data in references))
        logger.info("Runware references stored ahead of Draw model=%s count=%d seconds=%.1f",
                    model, len(references), time.monotonic() - started)
        model_response.created = int(time.time())
        model_response.data = []
        model_response._hidden_params["model"] = model
        model_response._hidden_params["custom_llm_provider"] = "runware"
        model_response._hidden_params["response_cost"] = 0.0
        model_response._hidden_params["runware_prefetched"] = len(references)
        model_response.model = f"runware/{model}"
        return model_response


def upstream_model_name(model: str) -> str:
    cleaned = (model or "").strip().strip("/").removeprefix("runware/")
    if cleaned not in SUPPORTED_MODELS:
        raise RunwareImageError(status_code=400, phase="request_validation", model=cleaned or "<missing>",
                                detail="unsupported Runware image model")
    return cleaned


def inference_task(model: str, prompt: str, params: dict[str, Any]) -> dict[str, Any]:
    """The exact Runware task, from Canary's frozen manifest.

    LiteLLM removes standard image arguments (size, quality) for custom
    providers, so dimensions and controls travel in ``canary_wire_request``.
    """
    if not prompt:
        raise RunwareImageError(status_code=400, phase="request_validation", model=model,
                                detail="prompt is required")
    wire = params.get("canary_wire_request")
    if not isinstance(wire, str):
        raise RunwareImageError(status_code=400, phase="request_validation", model=model,
                                detail="missing frozen wire manifest")
    try:
        manifest = json.loads(wire)
        width, height = int(manifest["width"]), int(manifest["height"])
        controls = dict(manifest["controls"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RunwareImageError(status_code=400, phase="request_validation", model=model,
                                detail=f"invalid frozen wire manifest ({type(exc).__name__})") from None
    allowed = _MINIMAX_CONTROLS if model in MINIMAX_MODELS else _ALLOWED_CONTROLS
    unknown = sorted(set(controls) - allowed)
    if unknown:
        raise RunwareImageError(status_code=400, phase="request_validation", model=model,
                                detail=f"unsupported controls {unknown}")
    if width <= 0 or height <= 0 or width % 16 or height % 16:
        raise RunwareImageError(status_code=400, phase="request_validation", model=model,
                                detail=f"invalid size {width}x{height}")
    if str(controls.get("output_format", "png")).lower() != "png":
        # Runware defaults to JPG; Canary artifacts are PNG.
        raise RunwareImageError(status_code=400, phase="request_validation", model=model,
                                detail="only png output is supported")
    if int(controls.get("n", 1)) != 1:
        raise RunwareImageError(status_code=400, phase="request_validation", model=model,
                                detail="exactly one image per request")
    if model in MINIMAX_MODELS:
        _check_minimax_size(model, width, height)
        # promptOptimizer stays at its default (on): Runware requires it
        # whenever reference images are sent.
        settings: dict[str, Any] = {}
    else:
        settings = {"moderation": MODERATION}
        for key in ("quality", "background"):
            if key in controls:
                settings[key] = str(controls[key]).lower()
    task = {
        "taskType": "imageInference",
        "taskUUID": str(uuid.uuid4()),
        "model": SUPPORTED_MODELS[model],
        "positivePrompt": prompt,
        "width": width,
        "height": height,
        "settings": settings,
        "numberResults": 1,
        "outputType": "base64Data",
        "outputFormat": "PNG",
        "includeCost": True,
        "deliveryMethod": "sync",
        "safety": {"checkContent": False},
    }
    if not settings:
        del task["settings"]
    return task


def _check_minimax_size(model: str, width: int, height: int) -> None:
    sides_ok = all(MINIMAX_MIN_SIDE <= side <= MINIMAX_MAX_SIDE for side in (width, height))
    area_ok = MINIMAX_MIN_PIXELS <= width * height <= MINIMAX_MAX_PIXELS
    if not (sides_ok and area_ok and max(width, height) <= 3 * min(width, height)):
        raise RunwareImageError(status_code=400, phase="request_validation", model=model,
                                detail=f"size {width}x{height} is outside MiniMax H3 limits")


def reference_bytes(item: Any, index: int, *, model: str) -> bytes:
    """One reference's bytes. Unreadable references fail the request."""
    value = item[1] if isinstance(item, tuple) and len(item) > 1 else item
    data: Any = None
    if isinstance(value, (bytes, bytearray)):
        data = bytes(value)
    elif isinstance(value, str) and Path(value).is_file():
        data = Path(value).read_bytes()
    else:
        reader = getattr(value, "read", None)
        if callable(reader):
            seeker = getattr(value, "seek", None)
            try:
                if callable(seeker):
                    seeker(0)
                data = reader()
            finally:
                if callable(seeker):
                    seeker(0)
    if isinstance(data, bytearray):
        data = bytes(data)
    if not isinstance(data, bytes) or not data:
        raise RunwareImageError(status_code=400, phase="request_validation", model=model,
                                detail=f"reference {index} has no readable image bytes")
    return data


async def generate(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    task: dict[str, Any],
    references: list[bytes],
    *,
    model: str,
    cache: _MediaCache | None = None,
) -> dict[str, Any]:
    """Run one inference task and return its result entry.

    The only second submission is after Runware rejected a stale reference
    UUID synchronously, when the first task provably never ran.
    """
    cache = cache or MEDIA_CACHE
    stale_retry_used = False
    while True:
        media = list(await asyncio.gather(*(
            cache.resolve(data, lambda d: _upload(http, headers, d, model=model)) for data in references
        )))
        if media:
            task["inputs"] = {"referenceImages": media}
        try:
            return await _submit(http, headers, task, model=model)
        except RunwareImageError as exc:
            if exc.code != _STALE_REFERENCE_CODE or stale_retry_used or not media:
                raise
            stale_retry_used = True
            logger.warning("Runware rejected a stored reference; re-uploading model=%s task_uuid=%s",
                           model, task["taskUUID"])
            for media_uuid in media:
                cache.evict(media_uuid)
            task["taskUUID"] = str(uuid.uuid4())


async def _upload(http: httpx.AsyncClient, headers: dict[str, str], data: bytes, *, model: str) -> str:
    """Store one reference. Uploads are free and content-addressed, so a
    repeated upload after a lost answer cannot charge or duplicate."""
    media = "data:image/png;base64," + base64.b64encode(data).decode("ascii")
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        try:
            response = await http.post(
                RUNWARE_API, headers=headers, timeout=UPLOAD_TIMEOUT_S,
                json=[{"taskType": "mediaStorage", "taskUUID": str(uuid.uuid4()),
                       "operation": "upload", "media": media}],
            )
        except httpx.RequestError as exc:
            if attempt == UPLOAD_ATTEMPTS:
                raise RunwareImageError(status_code=502, phase="upload", model=model,
                                        detail=type(exc).__name__) from None
            await asyncio.sleep(1.0)
            continue
        body = _json(response)
        entry = _first(body, "data")
        if response.status_code < 400 and isinstance(entry, dict) and entry.get("mediaUUID"):
            return str(entry["mediaUUID"])
        if response.status_code < 500 or attempt == UPLOAD_ATTEMPTS:
            raise RunwareImageError(status_code=502 if response.status_code < 400 else response.status_code,
                                    phase="upload", model=model, upstream_status=response.status_code,
                                    code=_error_code(body), detail=_error_detail(body))
        await asyncio.sleep(1.0)
    raise AssertionError("upload loop exhausted without a result")


async def _submit(
    http: httpx.AsyncClient, headers: dict[str, str], task: dict[str, Any], *, model: str,
) -> dict[str, Any]:
    task_uuid = task["taskUUID"]
    submitted_at = time.monotonic()
    try:
        response = await http.post(RUNWARE_API, headers=headers, json=[task])
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
        # No connection was established, so Runware cannot have the task.
        raise RunwareImageError(status_code=503, phase="submit_connect", model=model,
                                task_uuid=task_uuid, detail=type(exc).__name__) from None
    except httpx.RequestError as exc:
        logger.warning("Runware image answer lost; recovering model=%s task_uuid=%s error=%s",
                       model, task_uuid, type(exc).__name__)
        return await recover(http, headers, task_uuid, submitted_at, model=model)
    body = _json(response)
    entry = _first(body, "data")
    if response.status_code < 400 and isinstance(entry, dict) and entry.get("taskUUID") == task_uuid:
        logger.info("Runware image completed model=%s task_uuid=%s cost=%s",
                    model, task_uuid, entry.get("cost"))
        return entry
    code = _error_code(body)
    if code is not None:
        # An explicit error is a definite outcome, and failed tasks are not billed.
        logger.error("Runware image rejected model=%s status=%s task_uuid=%s code=%s detail=%s",
                     model, response.status_code, task_uuid, code, _error_detail(body) or "<none>")
        raise RunwareImageError(status_code=response.status_code if response.status_code >= 400 else 502,
                                phase="submit", model=model, upstream_status=response.status_code,
                                code=code, task_uuid=task_uuid, detail=_error_detail(body))
    # A proxy error page or an unexpected body says nothing about the task.
    logger.warning("Runware image answer unreadable; recovering model=%s status=%s task_uuid=%s",
                   model, response.status_code, task_uuid)
    return await recover(http, headers, task_uuid, submitted_at, model=model)


async def recover(
    http: httpx.AsyncClient,
    headers: dict[str, str],
    task_uuid: str,
    submitted_at: float,
    *,
    model: str,
    sleep=asyncio.sleep,
    clock=time.monotonic,
) -> dict[str, Any]:
    """Resolve a task whose answer was lost, without resubmitting it."""
    delay, max_delay = RECOVERY_POLL_S
    while True:
        state, payload = await task_details(http, headers, task_uuid)
        elapsed = clock() - submitted_at
        if state == "completed":
            logger.info("Runware image recovered model=%s task_uuid=%s after %.0fs", model, task_uuid, elapsed)
            return payload
        if state == "failed":
            raise RunwareImageError(status_code=502, phase="submit", model=model, code=_error_code(payload),
                                    task_uuid=task_uuid, detail=_error_detail(payload))
        if state == "not_found" and elapsed >= NOT_FOUND_GRACE_S:
            # Not a proof that the task never ran; the outcome stays unknown.
            raise RunwareImageError(status_code=502, phase="unknown_outcome", model=model,
                                    task_uuid=task_uuid, detail="task not found after grace period")
        if elapsed >= RECOVERY_TIMEOUT_S:
            raise RunwareImageError(status_code=504, phase="unknown_outcome", model=model,
                                    task_uuid=task_uuid, detail=f"unresolved after {RECOVERY_TIMEOUT_S:.0f}s")
        await sleep(delay)
        delay = min(delay * 1.5, max_delay)


async def task_details(
    http: httpx.AsyncClient, headers: dict[str, str], task_uuid: str,
) -> tuple[str, dict[str, Any]]:
    """``completed`` (result entry), ``failed``, ``pending``, ``not_found`` or
    ``lookup_error``. Lookups are reads and never resubmit the task."""
    try:
        response = await http.post(RUNWARE_API, headers=headers,
                                   json=[{"taskType": "getTaskDetails", "taskUUID": task_uuid}])
    except httpx.RequestError:
        return "lookup_error", {}
    body = _json(response)
    if response.status_code >= 400:
        if _error_code(body) == "taskNotFound":
            return "not_found", body
        return "lookup_error", body
    details = _first(body, "data")
    answer = details.get("response") if isinstance(details, dict) else None
    if not isinstance(answer, dict):
        return "pending", {}
    if answer.get("errors"):
        return "failed", answer
    entry = _first(answer, "data")
    if isinstance(entry, dict) and entry.get("imageUUID"):
        return "completed", entry
    return "pending", {}


async def _image_bytes(
    http: httpx.AsyncClient, entry: dict[str, Any], *, model: str, task_uuid: str,
) -> bytes:
    """The PNG from a result entry: inline from the task's own answer, or from
    the public image URL for a recovered task (``getTaskDetails`` returns a
    placeholder in place of the base64 payload)."""
    encoded = entry.get("imageBase64Data")
    data: bytes | None = None
    if isinstance(encoded, str) and len(encoded) > 64:
        try:
            data = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise RunwareImageError(status_code=502, phase="result", model=model, task_uuid=task_uuid,
                                    detail="image is not base64") from None
    elif entry.get("imageUUID"):
        url = entry.get("imageURL") or RUNWARE_IMAGE_URL.format(image_uuid=entry["imageUUID"])
        for attempt in range(1, 4):
            try:
                response = await http.get(str(url))
            except httpx.RequestError as exc:
                if attempt == 3:
                    raise RunwareImageError(status_code=502, phase="result", model=model, task_uuid=task_uuid,
                                            detail=f"download {type(exc).__name__}") from None
                await asyncio.sleep(1.0)
                continue
            if response.status_code < 400:
                data = response.content
                break
            if attempt == 3 or response.status_code < 500:
                raise RunwareImageError(status_code=502, phase="result", model=model, task_uuid=task_uuid,
                                        upstream_status=response.status_code, detail="download failed")
            await asyncio.sleep(1.0)
    if not data or not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise RunwareImageError(status_code=502, phase="result", model=model, task_uuid=task_uuid,
                                detail="result is not a PNG image")
    return data


def _cost(entry: dict[str, Any]) -> float | None:
    value = entry.get("cost")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        if value is not None:
            logger.error("Runware result has invalid cost task_uuid=%s", entry.get("taskUUID"))
        return None
    return float(value)


def _headers(api_key: str | None) -> dict[str, str]:
    key = (api_key or os.environ.get("RUNWARE_API_KEY") or "").strip()
    if not key:
        raise RunwareImageError(status_code=500, phase="request_validation", model="<config>",
                                detail="RUNWARE_API_KEY is not set")
    return {"Authorization": f"Bearer {key}"}


def _json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except (TypeError, ValueError):
        return {}
    return body if isinstance(body, dict) else {}


def _first(body: dict[str, Any], key: str) -> Any:
    items = body.get(key)
    return items[0] if isinstance(items, list) and items else None


def _error_code(body: dict[str, Any]) -> str | None:
    error = _first(body, "errors")
    code = error.get("code") if isinstance(error, dict) else None
    return _redact_text(str(code))[:80] if code else None


def _error_detail(body: dict[str, Any]) -> str | None:
    error = _first(body, "errors")
    if not isinstance(error, dict):
        return None
    values = [f"{key}={_redact_text(str(error[key]))}" for key in ("parameter", "message") if error.get(key)]
    return "; ".join(values)[:600] or None


def _redact_text(value: str) -> str:
    text = " ".join(value.split())
    text = _URI_RE.sub("<redacted-uri>", text)
    return text[:400]


runware_image_llm = RunwareImageLLM()

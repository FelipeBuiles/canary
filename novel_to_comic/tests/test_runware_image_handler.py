import asyncio
import base64
import hashlib
import json

import httpx
import pytest

from litellm_handlers import runware_provider as rw

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
REF_A = b"reference-a"
REF_B = b"reference-b"


def _wire(width=1024, height=1536, controls=(("quality", "medium"), ("output_format", "png"), ("n", 1))):
    return {"canary_wire_request": json.dumps({"width": width, "height": height,
                                               "controls": [list(pair) for pair in controls]})}


class _Response:
    def __init__(self, status_code, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON")
        return self._payload


def _completed(task_uuid, *, inline=True, cost=0.05647):
    entry = {"taskType": "imageInference", "taskUUID": task_uuid, "imageUUID": "image-1", "cost": cost}
    entry["imageBase64Data"] = base64.b64encode(PNG).decode() if inline else "<placeholder>"
    return entry


class _Runware:
    """Fake Runware REST endpoint, scripted per task type."""

    def __init__(self, inference=(), details=(), downloads=()):
        self.inference = list(inference)
        self.details = list(details)
        self.downloads = list(downloads)
        self.uploads = []
        self.tasks = []
        self.lookups = []
        self.gets = []

    async def post(self, url, headers=None, json=None, timeout=None):
        task = json[0]
        kind = task["taskType"]
        if kind == "mediaStorage":
            self.uploads.append(task["media"])
            media_uuid = f"media-{len(self.uploads)}"
            await asyncio.sleep(0)
            return _Response(200, {"data": [{"mediaUUID": media_uuid}]})
        if kind == "imageInference":
            self.tasks.append(dict(task))
            outcome = self.inference.pop(0)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome(task) if callable(outcome) else outcome
        if kind == "getTaskDetails":
            self.lookups.append(task["taskUUID"])
            outcome = self.details.pop(0)
            return outcome(task) if callable(outcome) else outcome
        raise AssertionError(kind)

    async def get(self, url):
        self.gets.append(url)
        return self.downloads.pop(0)


def _ok(task):
    return _Response(200, {"data": [_completed(task["taskUUID"])]})


def _error(status, code, **extra):
    return _Response(status, {"data": [], "errors": [{"code": code, "message": "nope", **extra}]})


def _generate(client, refs=(), **params):
    task = rw.inference_task("gpt-image-2.5-sunburst", "draw the page", params or _wire())
    return task, asyncio.run(rw.generate(client, {"Authorization": "Bearer k"}, task, list(refs),
                                         model="gpt-image-2.5-sunburst", cache=rw._MediaCache()))


def test_task_carries_frozen_controls_and_quality_safeguards():
    task = rw.inference_task("gpt-image-2.5-sunburst", "page", _wire())

    assert task["model"] == "openai:gpt-image@2.5-sunburst"
    assert (task["width"], task["height"]) == (1024, 1536)
    assert task["settings"] == {"moderation": "low", "quality": "medium"}
    # Runware defaults to JPG and to URL delivery; Canary needs exact PNG bytes.
    assert task["outputFormat"] == "PNG" and task["outputType"] == "base64Data"
    assert task["includeCost"] is True and task["deliveryMethod"] == "sync"
    assert task["safety"] == {"checkContent": False}
    assert task["numberResults"] == 1


@pytest.mark.parametrize(("params", "detail"), [
    ({}, "missing frozen wire manifest"),
    (_wire(controls=(("seed", 3),)), "unsupported controls ['seed']"),
    (_wire(controls=(("output_format", "jpeg"),)), "only png output"),
    (_wire(controls=(("n", 2),)), "exactly one image"),
    (_wire(width=1000), "invalid size 1000x1536"),
])
def test_invalid_requests_never_leave_the_gateway(params, detail):
    with pytest.raises(rw.RunwareImageError) as exc_info:
        rw.inference_task("gpt-image-2.5-sunburst", "page", params)

    assert exc_info.value.phase == "request_validation"
    assert detail in str(exc_info.value)


def test_unsupported_model_is_rejected():
    with pytest.raises(rw.RunwareImageError, match="unsupported Runware image model"):
        rw.upstream_model_name("runware/gpt-image-2")


def test_references_go_by_uploaded_media_uuid():
    client = _Runware(inference=[_ok])

    task, entry = _generate(client, refs=(REF_A, REF_B, REF_A))

    assert len(client.uploads) == 2
    assert client.tasks[0]["inputs"] == {"referenceImages": ["media-1", "media-2", "media-1"]}
    assert entry["taskUUID"] == task["taskUUID"]


def test_concurrent_requests_share_one_upload_per_reference():
    client = _Runware(inference=[_ok, _ok])
    cache = rw._MediaCache()

    async def both():
        tasks = [rw.inference_task("gpt-image-2.5-sunburst", "page", _wire()) for _ in range(2)]
        await asyncio.gather(*(rw.generate(client, {}, task, [REF_A], model="m", cache=cache) for task in tasks))

    asyncio.run(both())

    assert len(client.uploads) == 1
    assert [t["inputs"]["referenceImages"] for t in client.tasks] == [["media-1"], ["media-1"]]


def test_stale_reference_is_reuploaded_and_submitted_once_more():
    client = _Runware(inference=[_error(400, "failedToTransferImage", parameter="referenceImages[0]"), _ok])
    cache = rw._MediaCache()
    cache.put(hashlib.sha256(REF_A).hexdigest(), "expired-media")
    task = rw.inference_task("gpt-image-2.5-sunburst", "page", _wire())
    first_uuid = task["taskUUID"]

    asyncio.run(rw.generate(client, {}, task, [REF_A], model="m", cache=cache))

    assert [t["inputs"]["referenceImages"] for t in client.tasks] == [["expired-media"], ["media-1"]]
    assert client.tasks[1]["taskUUID"] != first_uuid


def test_a_second_stale_reference_rejection_is_not_retried():
    stale = _error(400, "failedToTransferImage")
    client = _Runware(inference=[stale, stale])

    with pytest.raises(rw.RunwareImageError) as exc_info:
        _generate(client, refs=(REF_A,))

    assert exc_info.value.code == "failedToTransferImage"
    assert len(client.tasks) == 2


def test_connect_failure_is_definitely_unsubmitted():
    client = _Runware(inference=[httpx.ConnectError("dns")])

    with pytest.raises(rw.RunwareImageError) as exc_info:
        _generate(client)

    assert exc_info.value.phase == "submit_connect"
    assert client.lookups == []


def test_explicit_runware_error_is_a_definite_outcome_with_its_code():
    client = _Runware(inference=[_error(402, "thirdPartyInsufficientCredits")])

    with pytest.raises(rw.RunwareImageError) as exc_info:
        _generate(client)

    error = exc_info.value
    assert (error.phase, error.upstream_status, error.code) == ("submit", 402, "thirdPartyInsufficientCredits")
    assert "Runware image submit failed for gpt-image-2.5-sunburst; upstream_status=402" in str(error)
    assert client.lookups == []


def test_lost_answer_is_recovered_by_task_uuid_without_resubmitting(monkeypatch):
    monkeypatch.setattr(rw, "RECOVERY_POLL_S", (0, 0))
    not_found = _error(400, "taskNotFound")
    pending = _Response(200, {"data": [{"taskType": "getTaskDetails", "response": None}]})
    client = _Runware(
        inference=[httpx.ReadTimeout("lost")],
        details=[not_found, pending,
                 lambda t: _Response(200, {"data": [{"response": {"data": [_completed(t["taskUUID"], inline=False)]}}]})],
        downloads=[_Response(200, content=PNG)],
    )
    task = rw.inference_task("gpt-image-2.5-sunburst", "page", _wire())

    async def run():
        entry = await rw.generate(client, {}, task, [], model="m", cache=rw._MediaCache())
        return entry, await rw._image_bytes(client, entry, model="m", task_uuid=task["taskUUID"])

    entry, data = asyncio.run(run())

    assert len(client.tasks) == 1
    assert client.lookups == [task["taskUUID"]] * 3
    assert client.gets == ["https://im.runware.ai/image/ii/image-1.png"]
    assert data == PNG and entry["cost"] == 0.05647


def test_task_never_found_after_grace_is_an_unknown_outcome():
    not_found = _error(400, "taskNotFound")
    client = _Runware(details=[not_found, not_found])
    clock = iter([10.0, 61.0])

    async def no_sleep(_):
        return None

    with pytest.raises(rw.RunwareImageError) as exc_info:
        asyncio.run(rw.recover(client, {}, "task-1", 0.0, model="m", sleep=no_sleep, clock=lambda: next(clock)))

    assert exc_info.value.phase == "unknown_outcome"
    assert exc_info.value.task_uuid == "task-1"


def test_recovered_failed_task_is_a_definite_outcome():
    failed = _Response(200, {"data": [{"response": {"errors": [{"code": "providerContentModerated"}]}}]})
    client = _Runware(details=[failed])

    with pytest.raises(rw.RunwareImageError) as exc_info:
        asyncio.run(rw.recover(client, {}, "task-1", 0.0, model="m"))

    assert (exc_info.value.phase, exc_info.value.code) == ("submit", "providerContentModerated")


def test_unreadable_answer_is_recovered_not_trusted(monkeypatch):
    monkeypatch.setattr(rw, "RECOVERY_POLL_S", (0, 0))
    client = _Runware(
        inference=[_Response(504, None)],
        details=[lambda t: _Response(200, {"data": [{"response": {"data": [_completed(t["taskUUID"])]}}]})],
    )

    _generate(client)

    assert len(client.tasks) == 1 and len(client.lookups) == 1


def test_non_png_result_is_rejected():
    with pytest.raises(rw.RunwareImageError) as exc_info:
        asyncio.run(rw._image_bytes(_Runware(), {"imageBase64Data": base64.b64encode(b"JFIF" * 40).decode()},
                                    model="m", task_uuid="t"))

    assert exc_info.value.phase == "result"


def test_response_reports_task_uuid_and_runware_cost(monkeypatch):
    client = _Runware(inference=[_ok])

    class _Client:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return client

        async def __aexit__(self, *exc):
            return False

    class _ImageResponse:
        def __init__(self):
            self._hidden_params = {}

    monkeypatch.setattr(rw.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(rw, "MEDIA_CACHE", rw._MediaCache())
    response = asyncio.run(rw.RunwareImageLLM().aimage_edit(
        model="runware/gpt-image-2.5-sunburst", image=[("ref.png", REF_A, "image/png")], prompt="page",
        model_response=_ImageResponse(), api_key="k", optional_params=_wire(),
    ))

    assert base64.b64decode(response.data[0].b64_json) == PNG
    assert response.provider_cost_usd == 0.05647
    assert response.provider_cost_source == "runware_cost"
    assert response.provider_request_id == client.tasks[0]["taskUUID"]
    assert response._hidden_params["custom_llm_provider"] == "runware"

import asyncio
import json

import httpx
import pytest

from litellm_handlers import fal_provider
from litellm_handlers.fal_provider import _build_payload, _fal_endpoint


@pytest.mark.parametrize(
    ("model", "has_images", "expected"),
    [
        (
            "openai/gpt-image-2.5/sunburst",
            False,
            "openai/gpt-image-2.5/sunburst/text-to-image",
        ),
        (
            "fal-queue/openai/gpt-image-2.5/sunburst",
            True,
            "openai/gpt-image-2.5/sunburst/edit",
        ),
    ],
)
def test_sunburst_uses_fal_operation_endpoint(model, has_images, expected):
    assert _fal_endpoint(model, has_images=has_images) == expected


@pytest.mark.parametrize("model", [
    "bytedance/seedream/v5/lite/edit", "fal-ai/flux-2-pro/edit",
    "openai/gpt-image-2.5/flare",
])
def test_fal_rejects_unlisted_models(model):
    with pytest.raises(fal_provider.FalQueueError, match="unsupported FAL model"):
        _fal_endpoint(model, has_images=False)


def test_sunburst_payload_preserves_custom_dimensions_and_controls():
    payload = _build_payload(
        "openai/gpt-image-2.5/sunburst/text-to-image",
        "a precise style proof",
        [],
        {
            "size": "1024x1280",
            "quality": "high",
            "output_format": "png",
            "n": 1,
        },
    )

    assert payload == {
        "prompt": "a precise style proof",
        "image_size": {"width": 1024, "height": 1280},
        "num_images": 1,
        "quality": "high",
        "output_format": "png",
    }


def test_wire_dimensions_are_used_when_gateway_sends_manifest_fields():
    payload = _build_payload(
        "openai/gpt-image-2.5/sunburst/text-to-image",
        "a style proof",
        [],
        {"canary_requested_width": "1024", "canary_requested_height": "1280"},
    )

    assert payload["image_size"] == {"width": 1024, "height": 1280}


def test_frozen_wire_controls_survive_litellm_custom_provider_filtering():
    payload = _build_payload(
        "openai/gpt-image-2.5/sunburst/text-to-image",
        "a style proof",
        [],
        {
            "canary_wire_request": json.dumps({
                "width": 1024,
                "height": 1280,
                "controls": [["quality", "medium"]],
            }),
        },
    )

    assert payload["image_size"] == {"width": 1024, "height": 1280}
    assert payload["quality"] == "medium"


def test_existing_remote_or_data_uri_references_are_not_double_encoded():
    data_uri = "data:image/png;base64,abc"
    assert _build_payload(
        "openai/gpt-image-2.5/sunburst/edit", "edit", [data_uri], {}
    )["image_urls"] == [data_uri]


class _Response:
    def __init__(self, status_code, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    @property
    def text(self):
        return str(self._payload or "")

    def json(self):
        if isinstance(self._payload, BaseException):
            raise self._payload
        return self._payload


class _GetClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, headers=None):
        self.calls.append((url, headers))
        return self.responses.pop(0)


def test_submit_dns_failure_reports_definitely_unsubmitted():
    class _Client:
        async def post(self, url, **kwargs):
            raise httpx.ConnectError("name resolution failed")

    with pytest.raises(fal_provider.FalQueueError) as exc_info:
        asyncio.run(fal_provider._submit(
            _Client(),
            "openai/gpt-image-2.5/sunburst/text-to-image",
            {"prompt": "test"},
            "fal-key",
        ))

    assert exc_info.value.phase == "submit_connect"
    assert exc_info.value.status_code == 503
    assert "name resolution failed" not in str(exc_info.value)


def test_status_poll_retries_transient_get_failures_without_resubmitting(monkeypatch):
    client = _GetClient([
        _Response(500, {"error": {"code": "temporary"}}),
        _Response(200, {"status": "COMPLETED"}),
    ])
    monkeypatch.setattr(fal_provider, "POLL_INTERVAL_S", 0)

    asyncio.run(fal_provider._poll(
        client,
        "https://queue.fal.run/status",
        "request-1",
        "fal-key",
        endpoint="openai/gpt-image-2.5/sunburst/text-to-image",
    ))

    assert len(client.calls) == 2


def test_failed_queue_status_keeps_request_id_and_redacts_urls(monkeypatch):
    client = _GetClient([_Response(200, {
        "status": "FAILED",
        "error": {
            "code": "provider_error",
            "message": "see https://example.invalid/result and data:image/png;base64,secret",
        },
    })])
    monkeypatch.setattr(fal_provider, "POLL_INTERVAL_S", 0)

    with pytest.raises(fal_provider.FalQueueError) as exc_info:
        asyncio.run(fal_provider._poll(
            client,
            "https://queue.fal.run/status",
            "request-2",
            "fal-key",
            endpoint="openai/gpt-image-2.5/sunburst/text-to-image",
        ))

    error = exc_info.value
    assert error.request_id == "request-2"
    assert "<redacted-uri>" in str(error)
    assert "secret" not in str(error)


def test_sync_mode_data_uri_result_does_not_make_a_second_network_request():
    client = _GetClient([])

    image = asyncio.run(fal_provider._download(
        client,
        "data:image/png;base64,aGVsbG8=",
        endpoint="openai/gpt-image-2.5/sunburst/text-to-image",
        request_id="request-3",
    ))

    assert image == b"hello"
    assert client.calls == []

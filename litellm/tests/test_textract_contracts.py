"""Pinned LiteLLM + AWS SDK contracts with no network or paid requests."""
import asyncio
import base64
import hashlib
import json
import struct
import time

import pytest

import litellm
from litellm_handlers import textract


def messages(**extra):
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 80, 20)
    return [{"role": "user", "content": json.dumps({"schema": "canary.crop-ocr/1",
        "image": base64.b64encode(png).decode(), "sha256": hashlib.sha256(png).hexdigest(),
        "attempt_id": "a" * 32, "expires_at": time.time()+20, **extra})}]


def test_pinned_litellm_custom_route(monkeypatch):
    requests = []
    def detect(request):
        requests.append(request)
        return {"status": "succeeded", "response": {"Blocks": [], "DetectDocumentTextModelVersion": "fixture"}}
    monkeypatch.setattr(textract, "detect", detect)
    monkeypatch.setattr(litellm, "custom_provider_map", [
        {"provider": "textract", "custom_handler": textract.textract_llm}])
    litellm.utils.custom_llm_setup()
    router = litellm.Router(model_list=[{"model_name": "ocr-textract",
        "litellm_params": {"model": "textract/detect-document-text"}}], num_retries=0)
    result = asyncio.run(router.acompletion(model="ocr-textract", messages=messages()))
    envelope = json.loads(result.choices[0].message.content)
    assert envelope["status"] == "succeeded"
    assert envelope["region"] == "us-east-1"
    assert envelope["response"]["Blocks"] == []
    assert len(requests) == 1


def test_envelope_rejects_expected_text_and_invalid_pixels():
    with pytest.raises(ValueError, match="envelope"):
        textract.parse_request(messages(expected="script"))
    with pytest.raises(ValueError, match="hash"):
        textract.parse_request(messages(sha256="0"*64))
    with pytest.raises(ValueError, match="PNG"):
        textract.parse_request(messages(image=base64.b64encode(b"no pixels").decode()))


def test_sdk_uses_scoped_credentials_region_and_no_retries(monkeypatch):
    monkeypatch.setenv("CANARY_TEXTRACT_ACCESS_KEY_ID", "fixture-access")
    monkeypatch.setenv("CANARY_TEXTRACT_SECRET_ACCESS_KEY", "fixture-secret")
    client = textract.client_for(3)
    try:
        assert client.meta.region_name == "us-east-1"
        assert client.meta.config.retries["total_max_attempts"] == 1
        assert client.meta.config.read_timeout == 3
        assert client._request_signer._credentials.access_key == "fixture-access"
    finally:
        client.close()


def test_generic_bedrock_credentials_are_not_used(monkeypatch):
    for key in ("CANARY_TEXTRACT_ACCESS_KEY_ID", "CANARY_TEXTRACT_SECRET_ACCESS_KEY", "CANARY_TEXTRACT_AWS_PROFILE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "bedrock-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "bedrock-secret")
    with pytest.raises(ValueError, match="scoped"):
        textract.client_for(3)


def test_expired_request_never_creates_sdk_client(monkeypatch):
    monkeypatch.setattr(textract, "client_for", lambda _: pytest.fail("expired request reached SDK"))
    result = textract.detect(textract.parse_request(messages(expires_at=time.time()-1)))
    assert result["status"] == "not_submitted"


def test_transport_failure_is_unknown_and_not_retried(monkeypatch):
    calls = []
    class Client:
        def detect_document_text(self, **kwargs):
            calls.append(kwargs)
            raise TimeoutError("ambiguous")
        def close(self):
            pass
    monkeypatch.setattr(textract, "client_for", lambda _: Client())
    monkeypatch.setattr(textract, "_next_start", 0)
    result = textract.detect(textract.parse_request(messages()))
    assert result["status"] == "outcome_unknown" and len(calls) == 1
    assert set(calls[0]) == {"Document"}
    assert set(calls[0]["Document"]) == {"Bytes"}


def test_cancellation_does_not_release_running_sdk_slot(monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    slots = threading.BoundedSemaphore(1)
    class Client:
        def detect_document_text(self, **kwargs):
            entered.set()
            assert release.wait(5)
            return {"Blocks": []}
        def close(self):
            pass
    monkeypatch.setattr(textract, "_slots", slots)
    monkeypatch.setattr(textract, "_next_start", 0)
    monkeypatch.setattr(textract, "client_for", lambda _: Client())
    async def exercise():
        task = asyncio.create_task(textract.textract_llm.acompletion(
            model="textract/detect-document-text", messages=messages(), model_response=litellm.ModelResponse()))
        try:
            assert await asyncio.to_thread(entered.wait, 3)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not slots.acquire(blocking=False)
        finally:
            release.set()
    asyncio.run(exercise())
    assert slots.acquire(blocking=False)
    slots.release()

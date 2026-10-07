"""Pixels-only Textract transport. No prompts, repair calls, fallback or retries."""
from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import math
import os
import re
import struct
import threading
import time
from typing import Any

try:
    from litellm.llms.custom_llm import CustomLLM
except ModuleNotFoundError:
    class CustomLLM:
        pass

MAX_BYTES = 4_000_000
MAX_PIXELS = 3_000_000
REGION = "us-east-1"
# Across event loops and accounts within the existing single gateway process.
_slots = threading.BoundedSemaphore(4)
_pace = threading.Lock()
_next_start = 0.0


def parse_request(messages: list[dict]) -> dict:
    if len(messages) != 1 or set(messages[0]) != {"role", "content"} or messages[0]["role"] != "user":
        raise ValueError("Textract accepts one pixels-only envelope")
    content = messages[0]["content"]
    if not isinstance(content, str) or len(content) > 5_400_000:
        raise ValueError("Textract envelope exceeds byte limit")
    value = json.loads(content)
    if not isinstance(value, dict) or set(value) != {
        "schema", "image", "sha256", "attempt_id", "expires_at",
    } or value["schema"] != "canary.crop-ocr/1":
        raise ValueError("Invalid Textract envelope")
    if not re.fullmatch(r"[a-f0-9]{32}", value["attempt_id"]):
        raise ValueError("Invalid Textract attempt")
    expires = value["expires_at"]
    if not isinstance(expires, (int, float)) or not math.isfinite(expires) or expires > time.time() + 31:
        raise ValueError("Invalid Textract deadline")
    image = base64.b64decode(value["image"], validate=True)
    if not 24 <= len(image) <= MAX_BYTES or image[:8] != b"\x89PNG\r\n\x1a\n" or image[12:16] != b"IHDR":
        raise ValueError("Textract requires bounded PNG bytes")
    width, height = struct.unpack(">II", image[16:24])
    if not (0 < width <= 10000 and 0 < height <= 10000 and width * height <= MAX_PIXELS):
        raise ValueError("Textract crop exceeds pixel limit")
    if hashlib.sha256(image).hexdigest() != value["sha256"]:
        raise ValueError("Textract crop hash mismatch")
    return {**value, "image": image}


def client_for(timeout: float):
    import boto3
    from botocore.config import Config

    key = os.environ.get("CANARY_TEXTRACT_ACCESS_KEY_ID")
    secret = os.environ.get("CANARY_TEXTRACT_SECRET_ACCESS_KEY")
    profile = os.environ.get("CANARY_TEXTRACT_AWS_PROFILE")
    if key and secret:
        session = boto3.Session(aws_access_key_id=key, aws_secret_access_key=secret,
            aws_session_token=os.environ.get("CANARY_TEXTRACT_SESSION_TOKEN"))
    elif profile and not key and not secret:
        session = boto3.Session(profile_name=profile)
    else:
        raise ValueError("Textract needs explicitly scoped gateway credentials")
    return session.client("textract", region_name=REGION, config=Config(
        connect_timeout=min(2.0, timeout), read_timeout=max(0.01, timeout),
        retries={"mode": "standard", "total_max_attempts": 1},
    ))


def detect(request: dict) -> dict:
    """Keep the slot until the SDK actually returns, including after cancellation."""
    global _next_start
    deadline = time.monotonic() + max(0, request["expires_at"] - time.time())
    remaining = deadline - time.monotonic()
    if remaining <= 0 or not _slots.acquire(timeout=remaining):
        return {"status": "not_submitted", "error_code": "deadline"}
    client = None
    try:
        try:
            client = client_for(remaining)
        except Exception:  # noqa: BLE001 -- SDK credential setup must fail closed, without leaking secrets.
            return {"status": "not_submitted", "error_code": "credentials_unavailable"}
        with _pace:
            wait = max(0, _next_start - time.monotonic())
            if time.monotonic() + wait >= deadline:
                return {"status": "not_submitted", "error_code": "deadline"}
            if wait:
                time.sleep(wait)
            _next_start = time.monotonic() + 0.2  # Smooth five starts/second.
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return {"status": "not_submitted", "error_code": "deadline"}
        if time.monotonic() >= deadline:
            return {"status": "not_submitted", "error_code": "deadline"}
        try:
            response = client.detect_document_text(Document={"Bytes": request["image"]})
            return {"status": "succeeded", "response": response}
        except Exception as exc:  # noqa: BLE001 -- Preserve uncertainty after any SDK transport failure.
            response = getattr(exc, "response", {})
            code = response.get("Error", {}).get("Code", "transport_error")
            # Only explicit rejections are known failures; everything else may have run.
            rejected = code in {"AccessDeniedException", "InvalidParameterException",
                "InvalidS3ObjectException", "UnsupportedDocumentException", "DocumentTooLargeException",
                "BadDocumentException", "ProvisionedThroughputExceededException", "ThrottlingException"}
            return {"status": "failed" if rejected else "outcome_unknown", "error_code": code,
                    "response": {"ResponseMetadata": response.get("ResponseMetadata", {})}}
    finally:
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()
        _slots.release()


class TextractLLM(CustomLLM):
    def completion(self, model: str, messages: list, model_response: Any, **kwargs):
        request = parse_request(messages)
        result = detect(request)
        return self._response(model_response, request, result)

    async def acompletion(self, model: str, messages: list, model_response: Any, **kwargs):
        request = parse_request(messages)
        # A cancelled coroutine must not release the SDK thread's shared slot.
        result = await asyncio.to_thread(detect, request)
        return self._response(model_response, request, result)

    @staticmethod
    def _response(model_response, request, result):
        envelope = {"schema": "canary.crop-ocr/1", "attempt_id": request["attempt_id"],
                    "sha256": request["sha256"], "region": REGION, **result}
        model_response.choices[0].message.content = json.dumps(envelope)
        model_response.choices[0].finish_reason = "stop"
        model_response.model = "textract/detect-document-text"
        # No fake token usage; Canary prices successful document units explicitly.
        model_response._hidden_params["response_cost"] = None
        return model_response


textract_llm = TextractLLM()

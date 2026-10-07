"""Exercise the pinned Bedrock transport without AWS credentials or provider spend."""
import asyncio
import json
import struct
import zlib
from datetime import datetime, timedelta, timezone
from importlib import resources
from pathlib import Path
from urllib.parse import unquote

import httpx
import litellm
import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
MODELS = ["bedrock-claude-opus-5-5", "bedrock-claude-sonnet-5-5", "bedrock-claude-haiku-5-5"]


def configure_login(monkeypatch, tmp_path, *, expired=False):
    from botocore.utils import JSONFileCache, LoginTokenLoader
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    config = tmp_path / "config"
    config.write_text("[profile offline]\nregion = us-east-1\nlogin_session = offline-login\n")
    cache = JSONFileCache(str(tmp_path / "cache"))
    loader = LoginTokenLoader(cache)
    key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    loader.save_token("offline-login", {
        "accessToken": {"accessKeyId": "offline-access", "secretAccessKey": "offline-secret",
                        "sessionToken": "offline-session", "accountId": "123456789012",
                        "expiresAt": (datetime.now(timezone.utc) + timedelta(
                            seconds=-60 if expired else 3600)).isoformat()},
        "refreshToken": "offline-refresh", "dpopKey": key, "clientId": "offline-client",
    })
    monkeypatch.setenv("AWS_CONFIG_FILE", str(config))
    monkeypatch.setenv("AWS_LOGIN_CACHE_DIRECTORY", str(tmp_path / "cache"))
    monkeypatch.setenv("AWS_PROFILE", "offline")
    monkeypatch.setenv("AWS_PROFILE_NAME", "offline")
    # Match the empty credential placeholders forwarded by base Compose.
    for name in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
                 "AWS_BEARER_TOKEN_BEDROCK"):
        monkeypatch.setenv(name, "")
    return loader


def event_frame(name, data):
    """Encode a real AWS eventstream frame, including both protocol checksums."""
    headers = b""
    for key, value in [(":message-type", "event"), (":event-type", name),
                       (":content-type", "application/json")]:
        key, value = key.encode(), value.encode()
        headers += bytes([len(key)]) + key + b"\x07" + struct.pack(">H", len(value)) + value
    payload = json.dumps(data).encode()
    prelude = struct.pack(">II", 16 + len(headers) + len(payload), len(headers))
    message = prelude + struct.pack(">I", zlib.crc32(prelude)) + headers + payload
    return message + struct.pack(">I", zlib.crc32(message))


@pytest.mark.parametrize("model", MODELS)
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("effort", ["low", "medium", "high"])
@pytest.mark.parametrize("auth", ["bearer", "sigv4", "login"])
def test_bedrock_preserves_native_schema_vision_effort_and_streaming(monkeypatch, tmp_path, model, stream, effort, auth):
    route = next(r for r in yaml.safe_load((ROOT / "litellm/config.yaml").read_text())["model_list"]
                 if r["model_name"] == model)
    assert "api_key" not in route["litellm_params"]
    assert route["litellm_params"]["model"] == f"bedrock/converse/global.anthropic.{model.removeprefix('bedrock-')}"
    monkeypatch.setattr(litellm, "model_cost", json.loads(resources.files("litellm").joinpath(
        "model_prices_and_context_window_backup.json").read_text()))
    monkeypatch.setattr(litellm, "drop_params", False)
    monkeypatch.setenv("AWS_REGION_NAME", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "offline-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "offline-secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "offline-session")
    monkeypatch.delenv("AWS_PROFILE_NAME", raising=False)
    if auth == "bearer":
        monkeypatch.setenv("AWS_BEARER_TOKEN_BEDROCK", "offline-token")
    else:
        monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    if auth == "login":
        configure_login(monkeypatch, tmp_path)
    usage = {"inputTokens": 15, "outputTokens": 3, "totalTokens": 18}
    sent = []

    async def send(self, request, **kwargs):
        sent.append(request)
        if stream:
            events = [
                ("messageStart", {"role": "assistant"}),
                ("contentBlockDelta", {"contentBlockIndex": 0, "delta": {
                    "reasoningContent": {"text": "Checking the page."}}}),
                ("contentBlockStop", {"contentBlockIndex": 0}),
                ("contentBlockDelta", {"contentBlockIndex": 1, "delta": {"text": '{"ok":true}'}}),
                ("contentBlockStop", {"contentBlockIndex": 1}),
                ("messageStop", {"stopReason": "end_turn"}),
                ("metadata", {"usage": usage, "metrics": {"latencyMs": 1}}),
            ]
            return httpx.Response(200, request=request,
                                  headers={"content-type": "application/vnd.amazon.eventstream"},
                                  content=b"".join(event_frame(name, data) for name, data in events))
        return httpx.Response(200, request=request, json={
            "output": {"message": {"role": "assistant", "content": [{"text": '{"ok":true}'}]}},
            "stopReason": "end_turn", "usage": usage, "metrics": {"latencyMs": 1},
        })

    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    schema = {"type": "object", "properties": {"ok": {"type": "boolean"}},
              "required": ["ok"], "additionalProperties": False}
    router = litellm.Router(model_list=[route])

    async def invoke():
        result = await router.acompletion(
            model=model, stream=stream, max_completion_tokens=4096,
            messages=[{"role": "system", "content": "Read the page."}, {"role": "user", "content": [
                {"type": "text", "text": "Check this image."},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
            ]}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            **({"stream_options": {"include_usage": True}} if stream else {}),
        )
        if stream:
            chunks = [chunk async for chunk in result]
            assert any(chunk.choices and chunk.choices[0].delta.reasoning_content for chunk in chunks)
            return litellm.stream_chunk_builder(chunks)
        return result

    result = asyncio.run(invoke())
    assert len(sent) == 1
    request = sent[0]
    suffix = "converse-stream" if stream else "converse"
    assert unquote(str(request.url)) == (
        f"https://bedrock-runtime.us-east-1.amazonaws.com/model/global.anthropic."
        f"{model.removeprefix('bedrock-')}/{suffix}"
    )
    if auth == "bearer":
        assert request.headers["authorization"] == "Bearer offline-token"
    else:
        assert request.headers["authorization"].startswith("AWS4-HMAC-SHA256 ")
        assert request.headers["x-amz-security-token"] == "offline-session"
    body = json.loads(request.content)
    assert body["inferenceConfig"] == {"maxTokens": 4096}
    assert body["additionalModelRequestFields"] == {
        "thinking": {"type": "adaptive", "display": "summarized"}, "output_config": {"effort": effort},
    }
    assert json.loads(body["outputConfig"]["textFormat"]["structure"]["jsonSchema"]["schema"]) == schema
    assert body["system"] == [{"text": "Read the page."}]
    assert body["messages"][0]["content"][1]["image"] == {"format": "png", "source": {"bytes": "AAAA"}}
    assert "toolConfig" not in body
    assert result.choices[0].message.content == '{"ok":true}'
    assert result.usage.prompt_tokens == 15
    assert result.usage.completion_tokens == 3


def test_native_login_refreshes_expired_credentials_and_updates_cache(monkeypatch, tmp_path):
    import boto3
    from botocore.stub import Stubber
    from litellm.llms.bedrock.base_aws_llm import BaseAWSLLM

    loader = configure_login(monkeypatch, tmp_path, expired=True)
    # Stub only the refresh API; profile discovery, CRT key parsing and cache
    # persistence run through the installed SDK without network access.
    signin = boto3.client("signin", region_name="us-east-1",
                          aws_access_key_id="offline", aws_secret_access_key="offline")
    with Stubber(signin) as stub:
        stub.add_response("create_oauth2_token", {"tokenOutput": {
            "accessToken": {"accessKeyId": "refreshed-access", "secretAccessKey": "refreshed-secret",
                            "sessionToken": "refreshed-session"},
            "tokenType": "aws_sigv4", "expiresIn": 900, "refreshToken": "refreshed-refresh",
        }}, {"tokenInput": {"clientId": "offline-client", "refreshToken": "offline-refresh",
                           "grantType": "refresh_token"}})
        credentials = BaseAWSLLM().get_credentials(aws_region_name="us-east-1")
        assert credentials.method == "login"
        monkeypatch.setattr(credentials._refresh_using.__self__, "_client_creator",
                            lambda *args, **kwargs: signin)
        frozen = credentials.get_frozen_credentials()
        assert frozen.access_key == "refreshed-access"
        assert frozen.token == "refreshed-session"
        saved = loader.load_token("offline-login")
        assert saved["refreshToken"] == "refreshed-refresh"
        assert saved["accessToken"]["sessionToken"] == "refreshed-session"
        stub.assert_no_pending_responses()

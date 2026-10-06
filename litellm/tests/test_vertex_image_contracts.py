"""Exercise the configured Vertex image route against the real gateway SDK."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")


def test_nano_banana_gateway_preserves_native_controls_and_prices_reported_usage(monkeypatch):
    import litellm
    from litellm.utils import custom_llm_setup
    from google.genai import types
    from litellm_handlers import vertex_multimodal as handler

    route = next(r for r in yaml.safe_load((ROOT / "litellm/config.yaml").read_text())["model_list"]
                 if r["model_name"] == "image-nano-banana-2.1")
    route["litellm_params"]["vertex_project"] = "offline-test"
    manifest = {
        "discriminator": "canary.provider-wire/3", "schema_version": 3,
        "requested_alias": "image-nano-banana-2.1", "expected_route": "nano_banana_21",
        "provider_key": "vertex-multimodal", "configured_provider_model": route["litellm_params"]["model"],
        "prompt_parts": ["A red circle."], "references": [], "edit_parent_indices": [],
        "width": 1024, "height": 1024, "structured_aspect": None,
        "controls": [["quality", "medium"]], "compiled_request_sha256": "c" * 64,
    }
    manifest["execution_fingerprint"] = hashlib.sha256(json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    png = b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR" + struct.pack(">II", 2048, 2048)
    sent = []

    def generate(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(
            candidates=[SimpleNamespace(content=SimpleNamespace(parts=[
                types.Part(inline_data=types.Blob(data=png, mime_type="image/png")),
            ]))],
            usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=8, candidates_token_count=1680, thoughts_token_count=200,
                total_token_count=1888,
                candidates_tokens_details=[types.ModalityTokenCount(modality="IMAGE", token_count=1680)],
            ),
        )

    clients = []

    def client(**kwargs):
        clients.append(kwargs)
        return SimpleNamespace(models=SimpleNamespace(generate_content=generate))

    monkeypatch.setattr(handler.genai, "Client", client)
    monkeypatch.setattr(litellm, "custom_provider_map", [
        {"provider": "vertex-multimodal", "custom_handler": handler.vertex_multimodal_llm},
    ])
    custom_llm_setup()
    router = litellm.Router(model_list=[route], num_retries=0)
    response = asyncio.run(router.aimage_generation(
        model="image-nano-banana-2.1", prompt="A red circle.",
        canary_wire_request=json.dumps(manifest), canary_requested_aspect=1.0,
    ))
    assert len(sent) == 1
    assert clients[0]["http_options"].retry_options.attempts == 1
    assert sent[0]["model"] == "gemini-nano-banana-2.1"
    config = sent[0]["config"].model_dump(exclude_none=True)
    assert config["image_config"] == {"image_size": "2K", "aspect_ratio": "1:1"}
    assert not {"temperature", "top_p", "top_k", "seed", "logprobs"} & config.keys()
    assert response.usage.cost == pytest.approx(1680 * 3e-5 + 8 * 1.5e-6 + 200 * 7.5e-6)
    assert response.usage.output_tokens == 1880
    assert response.model == "vertex_ai/gemini-nano-banana-2.1"

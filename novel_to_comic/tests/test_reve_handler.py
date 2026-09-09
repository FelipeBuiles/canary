"""LiteLLM Reve handler: ordinary v2 create wire format.

The application uses the direct adapter for layout-enabled panels. This file
covers the v2 create fallback used for ordinary generation/edit requests.
"""

import asyncio
import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from litellm_handlers.reve_provider import (  # noqa: E402
    ImageResponse,
    reve_llm,
)

_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\nfakepng").decode("ascii")


def _compiled(tmp_path, *, model, count, role="style"):
    from novel_to_comic.compiled_request import compile_generation_request
    from novel_to_comic.generation_input import GenerationPromptInput
    from novel_to_comic.image_models import image_model_profile
    from novel_to_comic.image_references import (
        AuthorityScope,
        ReferenceAsset,
        ReferencePlan,
        selection_fingerprint_hex,
    )

    selected = []
    for index in range(count):
        path = tmp_path / f"reference_{index}.png"
        path.write_bytes(f"reference {index}".encode())
        selected.append(
            ReferenceAsset(
                path=path,
                role=role,
                entity_id=None,
                appearance_state_id=None,
                authority_scope=AuthorityScope.CONTEXTUAL,
                preserve_facets=(),
                ignore_facets=(),
                pose=None,
                content_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                lineage_parent_sha256=None,
            )
        )
    selected_tuple = tuple(selected)
    profile = image_model_profile(model)
    return compile_generation_request(
        prompt=GenerationPromptInput(
            full_prompt="A complete illustrated page.",
            width=1152,
            height=2048,
        ),
        reference_plan=ReferencePlan(
            expected_route=profile.route,
            selected=selected_tuple,
            dropped=(),
            selection_fingerprint=selection_fingerprint_hex(selected_tuple),
        ),
        route_profile=profile,
        requested_alias=model,
        configured_provider_model=model,
        asset_kind="labs_image",
    )


class _MockResponse:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def _capture_post(monkeypatch, payload=None):
    captured = {}

    async def mock_post(client, url, **kwargs):
        captured["url"] = url
        captured["payload"] = kwargs.get("json")
        return _MockResponse(payload or {"image": _PNG_B64, "request_id": "req_1"})

    monkeypatch.setattr("httpx.AsyncClient.post", mock_post)
    monkeypatch.setenv("REVE_API_KEY", "test_key")
    return captured


def test_create_uses_v2_prompt_aspect_and_fit_postprocessing(monkeypatch, tmp_path):
    from novel_to_comic.image_models import GATEWAY_IMAGE_REVE
    from novel_to_comic.provider_wire import compile_provider_wire_request

    captured = _capture_post(monkeypatch)
    wire = compile_provider_wire_request(
        _compiled(tmp_path, model=GATEWAY_IMAGE_REVE, count=0)
    )
    asyncio.run(reve_llm.aimage_generation(
        model="reve/create",
        prompt="ignored: wire owns the prompt",
        api_key="test_key",
        api_base=None,
        model_response=ImageResponse(),
        optional_params={
            "canary_wire_request": wire.to_json(),
        },
        logging_obj=None,
    ))
    assert captured["url"] == "https://api.reve.com/v2/image/create"
    payload = captured["payload"]
    assert payload["prompt"] == wire.prompt_parts[0]
    assert payload["aspect_ratio"] == "9:16"
    assert payload["postprocessing"] == [{"process": "fit_image", "max_dim": 2048}]
    assert "width" not in payload
    assert "height" not in payload


@pytest.mark.parametrize("edit_parent_indices", [(), (0,)])
def test_edit_uses_v2_raw_references_and_frame_markers(monkeypatch, tmp_path, edit_parent_indices):
    from novel_to_comic.image_models import GATEWAY_IMAGE_REVE
    from novel_to_comic.provider_wire import compile_provider_wire_request

    captured = _capture_post(monkeypatch)
    wire = compile_provider_wire_request(
        _compiled(tmp_path, model=GATEWAY_IMAGE_REVE, count=2, role="subject"),
        edit_parent_indices=edit_parent_indices,
    )
    files = [
        (str(ref.source_path), Path(ref.source_path).read_bytes())
        for ref in wire.references
    ]
    asyncio.run(reve_llm.aimage_edit(
        model="reve/create",
        image=files,
        prompt="ignored: wire owns the prompt",
        model_response=ImageResponse(),
        api_key="test_key",
        optional_params={"canary_wire_request": wire.to_json()},
    ))
    assert captured["url"] == "https://api.reve.com/v2/image/create"
    payload = captured["payload"]
    assert [reference.keys() for reference in payload["references"]] == [
        {"data"}, {"data"}
    ]
    assert [reference["data"] for reference in payload["references"]] == [
        base64.b64encode(Path(ref.source_path).read_bytes()).decode("ascii")
        for ref in wire.references
    ]
    assert payload["prompt"] == wire.prompt_parts[0]
    assert payload["aspect_ratio"] == wire.structured_aspect
    assert payload["postprocessing"] == [{"process": "fit_image", "max_dim": 2048}]
    assert "<frame>0</frame>" in payload["prompt"]
    assert "<frame>1</frame>" in payload["prompt"]
    assert "width" not in payload
    assert "height" not in payload


def test_content_violation_raises(monkeypatch, tmp_path):
    from novel_to_comic.image_models import GATEWAY_IMAGE_REVE
    from novel_to_comic.provider_wire import compile_provider_wire_request

    _capture_post(monkeypatch, payload={"content_violation": True, "request_id": "req_v"})
    wire = compile_provider_wire_request(
        _compiled(tmp_path, model=GATEWAY_IMAGE_REVE, count=0)
    )
    with pytest.raises(ValueError, match="content violation"):
        asyncio.run(reve_llm.aimage_generation(
            model="reve/create",
            prompt="p",
            api_key="test_key",
            api_base=None,
            model_response=ImageResponse(),
            optional_params={"canary_wire_request": wire.to_json()},
            logging_obj=None,
        ))


@pytest.mark.parametrize("model", ["image-reve", "image-balanced"])
def test_core_wire_crosses_gateway_with_exact_parent_references(tmp_path, model):
    from litellm_handlers.provider_wire import (
        exact_vertex_contents,
        parse_provider_wire,
        verify_wire_images,
    )
    from novel_to_comic.provider_wire import compile_provider_wire_request

    wire = compile_provider_wire_request(
        _compiled(tmp_path, model=model, count=2, role="subject"),
        edit_parent_indices=(1,),
    )
    manifest = parse_provider_wire(wire.to_json())
    images = [Path(ref.source_path).read_bytes() for ref in wire.references]
    verify_wire_images(manifest, images)
    assert manifest["edit_parent_indices"] == [1]
    assert exact_vertex_contents(manifest, images) == [
        images[0], wire.references[0].instruction,
        images[1], wire.references[1].instruction,
        *wire.prompt_parts,
    ]
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_wire_images(manifest, images[::-1])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("discriminator", "canary.provider-wire/2"),
        ("schema_version", 2),
        ("schema_version", 3.0),
        ("edit_parent_indices", None),
        ("edit_parent_indices", [True]),
        ("edit_parent_indices", ["0"]),
        ("edit_parent_indices", [-1]),
        ("edit_parent_indices", [1]),
        ("edit_parent_indices", [0, 0]),
        ("compiled_request_sha256", "not-a-digest"),
        ("width", 0),
        ("references", {}),
    ],
)
def test_gateway_rejects_invalid_schema_even_with_recomputed_hash(tmp_path, field, value):
    from litellm_handlers.provider_wire import parse_provider_wire
    from novel_to_comic.provider_wire import compile_provider_wire_request

    wire = compile_provider_wire_request(
        _compiled(tmp_path, model="image-reve", count=1, role="subject")
    )
    manifest = json.loads(wire.to_json())
    manifest[field] = value
    projection = {key: value for key, value in manifest.items() if key != "execution_fingerprint"}
    if isinstance(projection["references"], list):
        projection["references"] = [
            {key: value for key, value in ref.items() if key != "source_path"}
            for ref in projection["references"]
        ]
    manifest["execution_fingerprint"] = hashlib.sha256(
        json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
    with pytest.raises(ValueError):
        parse_provider_wire(json.dumps(manifest))


def test_gateway_requires_explicit_parents_and_binds_them_to_hash(tmp_path):
    from litellm_handlers.provider_wire import parse_provider_wire
    from novel_to_comic.provider_wire import compile_provider_wire_request

    wire = compile_provider_wire_request(
        _compiled(tmp_path, model="image-reve", count=1, role="subject")
    )
    manifest = json.loads(wire.to_json())
    del manifest["edit_parent_indices"]
    with pytest.raises(ValueError, match="fields"):
        parse_provider_wire(json.dumps(manifest))
    manifest["edit_parent_indices"] = [0]
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        parse_provider_wire(json.dumps(manifest))


def test_gateway_rejects_style_reference_as_edit_parent(tmp_path):
    from dataclasses import replace

    from litellm_handlers.provider_wire import parse_provider_wire
    from novel_to_comic.provider_wire import compile_provider_wire_request

    wire = compile_provider_wire_request(
        _compiled(tmp_path, model="image-reve", count=1)
    )
    invalid = replace(wire, edit_parent_indices=(0,))
    invalid = replace(invalid, execution_fingerprint=invalid.recompute_execution_fingerprint())
    with pytest.raises(ValueError, match="non-style"):
        parse_provider_wire(invalid.to_json())

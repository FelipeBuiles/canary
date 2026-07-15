from __future__ import annotations

import hashlib
import sys
from dataclasses import replace
from pathlib import Path

import pytest
import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from novel_to_comic.compiled_request import compile_generation_request
from novel_to_comic.image_models import GATEWAY_IMAGE_BALANCED, GATEWAY_IMAGE_REVE, image_model_profile
from novel_to_comic.image_references import AuthorityScope, ReferenceAsset, ReferencePlan
from novel_to_comic.models.prompt import (
    ImagePrompt,
    LayoutBbox,
    LayoutRegion,
    PromptLayout,
    PromptSubject,
)
from novel_to_comic.provider_wire import (
    PROVIDER_WIRE_SCHEMA_VERSION,
    ProviderWireError,
    compile_provider_wire_request,
    materialize_wire_references,
)
from novel_to_comic.ai.providers.litellm_http import (
    _image_response_descriptor,
    _raise_safe_decode_error,
    _raise_safe_wire_phase_error,
    _safe_decode_error_descriptor,
    serialize_wire_request,
)
from novel_to_comic.ai.errors import AITransportError
from litellm_handlers.provider_wire import (
    exact_vertex_contents,
    parse_provider_wire,
    verify_wire_images,
)
from novel_to_comic.labs.storage import stage_provider_wire_request


def _compiled(
    tmp_path: Path,
    *,
    model: str,
    count: int = 1,
    layout: PromptLayout | None = None,
    layout_enabled: bool = True,
    width: int = 768,
    height: int = 1344,
):
    assets = []
    subjects = []
    for index in range(count):
        data = f"ref-{index}".encode()
        path = tmp_path / f"char_{index}" / "front.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        assets.append(ReferenceAsset(
            path=path, role="subject", entity_id=f"char_{index}",
            appearance_state_id=None, authority_scope=AuthorityScope.FULL_APPEARANCE,
            preserve_facets=("face", "hair", "build", "wardrobe", "anatomy"),
            ignore_facets=(), pose="front", content_sha256=hashlib.sha256(data).hexdigest(),
            lineage_parent_sha256=None, label=f"Person {index}",
        ))
        subjects.append(PromptSubject(
            character_id=f"char_{index}", name=f"Person {index}", identity=f"ANCHOR-{index}",
        ))
    route = image_model_profile(model)
    plan = ReferencePlan(route.route, tuple(assets), (), "f" * 64, ())
    prompt = ImagePrompt(
        prompt_version=1, planned_panel_id="scene_001:panel_001", scene_id="scene_001",
        panel_number=1, composition="medium shot", full_prompt="", subjects=subjects,
        layout=layout, width=width, height=height, steps=20,
    )
    return compile_generation_request(
        prompt=prompt, reference_plan=plan, route_profile=route,
        requested_alias=model, configured_provider_model=(
            "reve/create" if model == GATEWAY_IMAGE_REVE else "vertex-multimodal/gemini"
        ), selected_style_text="ink wash",
        layout_enabled=layout_enabled,
    )


@pytest.mark.parametrize("model", [GATEWAY_IMAGE_REVE, GATEWAY_IMAGE_BALANCED])
@pytest.mark.parametrize("count", [0, 1, 4])
def test_wire_is_deterministic_and_preserves_exact_semantics(tmp_path: Path, model: str, count: int):
    compiled = _compiled(tmp_path, model=model, count=count)
    wire = compile_provider_wire_request(compiled)
    assert wire.schema_version == PROVIDER_WIRE_SCHEMA_VERSION
    assert wire.compiled_request_sha256 == compiled.compiled_request_sha256
    assert [r.instruction for r in wire.references] == [
        i.semantic_instruction for i in compiled.reference_instructions
    ]
    assert wire == compile_provider_wire_request(compiled)
    if model == GATEWAY_IMAGE_REVE:
        for index in range(count):
            assert f"<frame>{index}</frame>" in wire.prompt_parts[0]
    else:
        assert wire.prompt_parts == (compiled.final_prompt,)


def test_reve_layout_wire_projects_hierarchy_and_reference_binding(tmp_path: Path):
    layout = PromptLayout(
        prompt="A person in a room",
        regions=[
            LayoutRegion(
                label="person",
                prompt="a standing person",
                bbox=LayoutBbox(x0=0.1, y0=0.1, x1=0.6, y1=0.95),
                reference_key="char_0",
                region_type="coarse_detail",
            ),
            LayoutRegion(
                label="face",
                prompt="the person's face",
                bbox=LayoutBbox(x0=0.2, y0=0.15, x1=0.45, y1=0.35),
                parent="person",
                region_type="face",
            ),
        ],
    )
    compiled = _compiled(
        tmp_path,
        model=GATEWAY_IMAGE_REVE,
        count=1,
        layout=layout,
    )
    wire = compile_provider_wire_request(compiled)

    assert wire.layout is not None
    assert wire.prompt_parts != (compiled.final_prompt,)
    assert "<frame>0</frame>" in wire.prompt_parts[0]
    assert wire.layout["normalized_edit_instruction"] == compiled.final_prompt
    assert wire.layout["width"] % 32 == 0
    assert wire.layout["height"] % 32 == 0
    assert 3072 * 2560 <= wire.layout["width"] * wire.layout["height"] <= 4096 * 4096
    regions = {region["label"]: region for region in wire.layout["regions"]}
    assert regions["person"]["image_index"] == 0
    assert regions["person"]["region_type"] == "coarse_detail"
    assert regions["face"]["parent"] == "person"
    assert regions["face"]["region_type"] == "face"
    assert all("reference_key" not in region for region in wire.layout["regions"])


def test_layout_is_deeply_immutable_after_fingerprinting(tmp_path: Path):
    layout = PromptLayout(
        regions=[
            LayoutRegion(label="person", prompt="a person"),
            LayoutRegion(label="room", prompt="a room"),
        ],
    )
    wire = compile_provider_wire_request(
        _compiled(tmp_path, model=GATEWAY_IMAGE_REVE, count=1, layout=layout)
    )
    with pytest.raises(TypeError, match="immutable|does not support"):
        wire.layout["regions"][0]["label"] = "changed"
    with pytest.raises((TypeError, AttributeError)):
        wire.layout["regions"].append({"label": "new"})
    with pytest.raises(TypeError):
        dict.__setitem__(wire.layout["regions"][0], "label", "changed")
    with pytest.raises(TypeError):
        list.append(wire.layout["regions"], {"label": "new"})
    assert wire.execution_fingerprint == wire.recompute_execution_fingerprint()


def test_layout_rollout_flag_omits_stored_layout(tmp_path: Path):
    layout = PromptLayout(
        regions=[
            LayoutRegion(label="person", prompt="a person"),
            LayoutRegion(label="room", prompt="a room"),
        ],
    )
    compiled = _compiled(
        tmp_path,
        model=GATEWAY_IMAGE_REVE,
        count=1,
        layout=layout,
        layout_enabled=False,
    )
    wire = compile_provider_wire_request(compiled)
    assert compiled.layout is None
    assert wire.layout is None
    assert "<frame>0</frame>" in wire.prompt_parts[0]


@pytest.mark.parametrize(
    ("width", "height", "expected"),
    [(819, 1024, "4:5"), (1024, 819, "5:4"), (512, 1024, "1:2")],
)
def test_reve_wire_uses_v2_native_aspect_set(
    tmp_path: Path, width: int, height: int, expected: str,
):
    wire = compile_provider_wire_request(
        _compiled(
            tmp_path,
            model=GATEWAY_IMAGE_REVE,
            width=width,
            height=height,
        )
    )
    assert wire.structured_aspect == expected


def test_materialization_rejects_digest_mismatch_without_shifting(tmp_path: Path):
    wire = compile_provider_wire_request(_compiled(tmp_path, model=GATEWAY_IMAGE_REVE, count=2))
    Path(wire.references[0].source_path).write_bytes(b"changed")
    with pytest.raises(ProviderWireError, match="digest mismatch"):
        materialize_wire_references(wire)


def test_provider_affecting_change_changes_execution_fingerprint(tmp_path: Path):
    wire = compile_provider_wire_request(_compiled(tmp_path, model=GATEWAY_IMAGE_BALANCED))
    changed = replace(wire, prompt_parts=(wire.prompt_parts[0] + "!",), execution_fingerprint="")
    assert wire.execution_fingerprint != changed.recompute_execution_fingerprint()


def test_wire_manifest_round_trip(tmp_path: Path):
    wire = compile_provider_wire_request(_compiled(tmp_path, model=GATEWAY_IMAGE_BALANCED))
    assert type(wire).from_json(wire.to_json()) == wire


def test_litellm_wire_serialization_preserves_manifest_order_and_controls(tmp_path: Path):
    wire = compile_provider_wire_request(_compiled(tmp_path, model=GATEWAY_IMAGE_BALANCED, count=2))
    params, files = serialize_wire_request(wire)
    assert params["prompt"] == wire.prompt_parts[0]
    assert params["response_format"] == "b64_json"
    assert params["canary_requested_aspect"] == pytest.approx(768 / 1344)
    assert parse_provider_wire(params["canary_wire_request"])["execution_fingerprint"] == wire.execution_fingerprint
    assert [file[1][1] for file in files] == [b"ref-0", b"ref-1"]


def test_image_response_descriptor_redacts_payloads_and_signed_url_query():
    descriptor = _image_response_descriptor({
        "data": [{
            "b64_json": "secret-image-bytes",
            "url": "https://storage.example/var/image.png?token=secret",
            "revised_prompt": "safe",
        }],
        "model": "provider/model",
    })

    assert descriptor == {
        "response_keys": ["data", "model"],
        "item_keys": ["b64_json", "revised_prompt", "url"],
        "b64_length": 18,
        "url_scheme": "https",
        "url_host": "storage.example",
    }
    assert "secret" not in str(descriptor)


def test_decode_error_descriptor_never_includes_exception_message():
    error = OSError(20, "Not a directory: signed-token=secret")
    descriptor = _safe_decode_error_descriptor(error)
    assert descriptor == {"error_type": "NotADirectoryError", "errno": 20}
    assert "secret" not in str(descriptor)

    with pytest.raises(ValueError) as raised:
        _raise_safe_decode_error({"data": [{"url": "https://example/x?secret=1"}]}, error)
    assert raised.value.__cause__ is None
    assert "secret" not in str(raised.value)

    with pytest.raises(ValueError) as phase_error:
        _raise_safe_wire_phase_error("gateway_request", error)
    assert phase_error.value.__cause__ is None
    assert str(phase_error.value) == (
        'wire image transport failed ({"errno": 20, '
        '"error_type": "NotADirectoryError", "phase": "gateway_request"})'
    )


def test_gateway_transport_error_keeps_safe_http_diagnostics():
    request = httpx.Request("POST", "http://gateway/v1/images/generations")
    response = httpx.Response(
        504,
        request=request,
        json={"error": {"code": "upstream_timeout", "message": "secret prompt"}},
    )
    error = httpx.HTTPStatusError("Server returned 504", request=request, response=response)

    with pytest.raises(AITransportError) as raised:
        _raise_safe_wire_phase_error("gateway_request", error)

    assert raised.value.response is response
    assert raised.value.phase == "gateway_request"
    assert '"status_code": 504' in str(raised.value)
    assert '"provider_error_code": "upstream_timeout"' in str(raised.value)
    assert "secret prompt" not in str(raised.value)


def test_gateway_read_disconnect_has_actionable_safe_diagnostic():
    request = httpx.Request("POST", "http://gateway/v1/images/generations")
    error = httpx.ReadError("secret upstream detail", request=request)

    with pytest.raises(AITransportError) as raised:
        _raise_safe_wire_phase_error("gateway_request", error)

    message = str(raised.value)
    assert '"failure": "gateway disconnected before sending a response"' in message
    assert "secret upstream detail" not in message


def test_gateway_transport_error_exposes_allowlisted_aspect_detail():
    request = httpx.Request("POST", "http://gateway/v1/images/generations")
    response = httpx.Response(
        500,
        request=request,
        json={"error": {
            "code": "500",
            "message": (
                "litellm.APIConnectionError: Vertex image SDK does not support "
                "native aspect ratio controls; cannot safely generate the requested "
                "4:5 frame. Received Model Group=image-balanced"
            ),
        }},
    )
    error = httpx.HTTPStatusError(
        "failed", request=request, response=response,
    )

    with pytest.raises(AITransportError) as raised:
        _raise_safe_wire_phase_error("gateway_request", error)

    assert (
        '"provider_detail": "Vertex image SDK does not support native aspect '
        'ratio controls; cannot safely generate the requested 4:5 frame"'
        in str(raised.value)
    )
def test_isolated_handler_rejects_reordered_or_changed_uploads(tmp_path: Path):
    wire = compile_provider_wire_request(_compiled(tmp_path, model=GATEWAY_IMAGE_BALANCED, count=2))
    manifest = parse_provider_wire(wire.to_json())
    verify_wire_images(manifest, [("a", b"ref-0"), ("b", b"ref-1")])
    with pytest.raises(ValueError, match="digest mismatch"):
        verify_wire_images(manifest, [("b", b"ref-1"), ("a", b"ref-0")])


def test_isolated_vertex_parser_adds_no_prose_or_relabels(tmp_path: Path):
    wire = compile_provider_wire_request(_compiled(tmp_path, model=GATEWAY_IMAGE_BALANCED, count=2))
    manifest = parse_provider_wire(wire.to_json())
    parts = [object(), object()]
    contents = exact_vertex_contents(manifest, parts)
    assert contents == [
        parts[0], wire.references[0].instruction,
        parts[1], wire.references[1].instruction,
        wire.prompt_parts[0],
    ]


def test_labs_staging_preserves_complete_wire_manifest(tmp_path: Path):
    wire = compile_provider_wire_request(_compiled(tmp_path, model=GATEWAY_IMAGE_BALANCED, count=2))
    staged = stage_provider_wire_request(tmp_path / "projects", "run-1", wire)
    assert staged.execution_fingerprint == wire.execution_fingerprint
    assert [r.instruction for r in staged.references] == [r.instruction for r in wire.references]
    manifest = Path(staged.references[0].source_path).parent / "provider-wire.json"
    assert type(wire).from_json(manifest.read_text()) == staged

from __future__ import annotations

import hashlib
import sys
from dataclasses import replace
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from novel_to_comic.compiled_request import compile_generation_request
from novel_to_comic.image_models import GATEWAY_IMAGE_BALANCED, GATEWAY_IMAGE_REVE, image_model_profile
from novel_to_comic.image_references import AuthorityScope, ReferenceAsset, ReferencePlan
from novel_to_comic.models.prompt import ImagePrompt, PromptSubject
from novel_to_comic.provider_wire import (
    PROVIDER_WIRE_SCHEMA_VERSION,
    ProviderWireError,
    compile_provider_wire_request,
    materialize_wire_references,
)
from novel_to_comic.ai.providers.litellm_http import serialize_wire_request
from litellm_handlers.provider_wire import (
    exact_vertex_contents,
    parse_provider_wire,
    verify_wire_images,
)
from novel_to_comic.labs.storage import stage_provider_wire_request


def _compiled(tmp_path: Path, *, model: str, count: int = 1):
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
        width=768, height=1344, steps=20,
    )
    return compile_generation_request(
        prompt=prompt, reference_plan=plan, route_profile=route,
        requested_alias=model, configured_provider_model=(
            "reve/create" if model == GATEWAY_IMAGE_REVE else "vertex-multimodal/gemini"
        ), selected_style_text="ink wash",
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
            assert f"<img>{index}</img>" in wire.prompt_parts[0]
    else:
        assert wire.prompt_parts == (compiled.final_prompt,)


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
    assert parse_provider_wire(params["canary_wire_request"])["execution_fingerprint"] == wire.execution_fingerprint
    assert [file[1][1] for file in files] == [b"ref-0", b"ref-1"]


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
        wire.prompt_parts[0], wire.references[0].instruction, parts[0],
        wire.references[1].instruction, parts[1],
    ]


def test_labs_staging_preserves_complete_wire_manifest(tmp_path: Path):
    wire = compile_provider_wire_request(_compiled(tmp_path, model=GATEWAY_IMAGE_BALANCED, count=2))
    staged = stage_provider_wire_request(tmp_path / "projects", "run-1", wire)
    assert staged.execution_fingerprint == wire.execution_fingerprint
    assert [r.instruction for r in staged.references] == [r.instruction for r in wire.references]
    manifest = Path(staged.references[0].source_path).parent / "provider-wire.json"
    assert type(wire).from_json(manifest.read_text()) == staged

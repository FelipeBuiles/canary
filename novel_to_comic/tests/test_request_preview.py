from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

from novel_to_comic.frozen_requests import (
    invalidate_prepared_requests,
    load_frozen_request,
    submit_frozen_request,
    update_frozen_request_status,
)
from novel_to_comic.generation_request_preview import (
    compiled_request_context,
    frozen_request_preview,
)
from novel_to_comic.provider_wire import ProviderWireReference, ProviderWireRequest


def _wire(source: Path) -> ProviderWireRequest:
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    wire = ProviderWireRequest(
        discriminator="canary.provider-wire/1",
        schema_version=1,
        requested_alias="image-balanced",
        expected_route="gemini_flash_lite",
        configured_provider_model="vertex-multimodal/gemini-3.1-flash-lite-image",
        prompt_parts=("protected anchor sentinel",),
        references=(ProviderWireReference(
            index=0,
            source_path=str(source),
            content_sha256=digest,
            role="subject",
            role_label="subject:Mara",
            instruction="Use reference 0 for identity.",
            provider_binding="0",
            entity_id="char_001",
            appearance_state_id="battle-worn",
            authority_scope="full_appearance",
            preserve_facets=("face", "hair"),
            ignore_facets=("clothing",),
        ),),
        width=768,
        height=1024,
        structured_aspect=None,
        controls=(("quality", "medium"),),
        compiled_request_sha256="c" * 64,
        execution_fingerprint="",
    )
    return replace(wire, execution_fingerprint=wire.recompute_execution_fingerprint())


def test_frozen_preview_is_portable_and_does_not_expose_server_paths(tmp_path: Path):
    source = tmp_path / "refs" / "mara.png"
    source.parent.mkdir()
    source.write_bytes(b"mara")
    context = {
        "asset_kind": "panel",
        "asset_identity": "scene_001:panel_001",
        "prompt_source_sha256": "a" * 64,
        "semantic_prompt": {
            "sections": [{"kind": "anchors", "title": "Anchors", "lines": ["sentinel"]}],
            "final_prompt": "semantic sentinel",
            "protected_anchors": [{
                "kind": "character",
                "entity_id": "char_001",
                "name": "Mara",
                "appearance_state_id": "battle-worn",
                "text": "sentinel",
            }],
        },
    }
    frozen = submit_frozen_request(
        tmp_path, _wire(source), status="prepared", request_context=context,
    )

    loaded = load_frozen_request(tmp_path, frozen.request_id)
    preview = frozen_request_preview(loaded, include_dev_content=True)

    assert preview["state_label"] == "Prepared request"
    assert preview["exact"] is True
    assert preview["execution_fingerprint"] == frozen.execution_fingerprint
    assert preview["semantic_prompt"]["protected_anchors"][0]["text"] == "sentinel"
    assert preview["provider_wire"]["references"][0]["content_sha256"] == hashlib.sha256(b"mara").hexdigest()
    assert str(tmp_path) not in preview["wire_json"]
    assert str(source) not in preview["wire_json"]
    assert preview["provider_wire"]["references"][0]["source_path"].startswith("blobs/")


def test_draft_projection_is_explicitly_non_exact():
    draft = frozen_request_preview(None, draft={
        "prompt": "draft prompt",
        "warnings": ["preparation outstanding"],
    })

    assert draft == {
        "state_label": "Draft projection",
        "exact": False,
        "exactness": "non-exact",
        "warnings": ["preparation outstanding"],
        "draft": {"prompt": "draft prompt"},
    }


def test_compiled_context_has_no_reference_paths():
    class Compiled:
        asset_kind = "panel"
        asset_identity = "scene_001:panel_001"
        prompt_source_sha256 = "a" * 64
        final_prompt = "final"
        sections = ()
        protected_anchors = ()
        warnings = ()

    context = compiled_request_context(Compiled())
    assert context["asset_identity"] == "scene_001:panel_001"
    assert "path" not in str(context).lower()


def test_prepared_request_invalidation_and_completion_keep_execution_identity(tmp_path: Path):
    source = tmp_path / "ref.png"
    source.write_bytes(b"mara")
    frozen = submit_frozen_request(
        tmp_path,
        _wire(source),
        status="prepared",
        request_context={"asset_identity": "scene_001:panel_001"},
    )
    assert invalidate_prepared_requests(tmp_path, "other:panel_001") == []
    assert invalidate_prepared_requests(tmp_path, "scene_001:panel_001") == [frozen.request_id]
    invalidated = load_frozen_request(tmp_path, frozen.request_id)
    assert frozen_request_preview(invalidated)["exact"] is False

    submitted = submit_frozen_request(
        tmp_path,
        _wire(source),
        idempotency_key="submitted",
        request_context={"asset_identity": "scene_001:panel_001"},
    )
    update_frozen_request_status(tmp_path, submitted.request_id, "complete", result_link="draw/panel.png")
    output = tmp_path / "draw" / "panel.png"
    output.parent.mkdir()
    output.write_bytes(b"image")
    output.with_suffix(".png.meta.json").write_text(
        '{"actual_provider_model":"provider/actual","actual_dimensions":{"width":640,"height":832}}'
    )
    completed = frozen_request_preview(
        load_frozen_request(tmp_path, submitted.request_id),
        include_dev_content=True,
        project_dir=tmp_path,
    )
    assert completed["state_label"] == "Completed request"
    assert completed["execution_fingerprint"] == submitted.execution_fingerprint
    assert completed["actual_model"] == "provider/actual"
    assert completed["actual_dimensions"] == {"width": 640, "height": 832}

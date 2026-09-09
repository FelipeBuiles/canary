import asyncio
import hashlib
import io
from dataclasses import replace

import pytest
from PIL import Image

from novel_to_comic import asset_generation, codex_dev
from novel_to_comic.ai import codex_runtime
from novel_to_comic.ai.providers import codex_dev as provider_module
from novel_to_comic.ai.providers.codex_dev import CodexDevImageProvider, validate_codex_wire
from novel_to_comic.asset_generation import AbstractStyleProofInput, compile_non_panel_request, reference_plan_for_assets
from novel_to_comic.config import Config
from novel_to_comic.generation_input import GenerationPromptInput
from novel_to_comic.image_references import AuthorityScope, ReferenceAsset
from novel_to_comic.provider_wire import ProviderWireError, ProviderWireRequest


@pytest.fixture
def routed(monkeypatch):
    route = codex_dev.CodexRoute(reasoning_model="gpt-5.6-terra", image_model="gpt-image-2")
    for module in (codex_dev, asset_generation, provider_module):
        monkeypatch.setattr(module, "route_for", lambda kind, model: route)
    monkeypatch.setattr(provider_module, "assert_request_funding", lambda *args: None)
    return Config(image_model="image-quality")


def _png(color):
    output = io.BytesIO()
    Image.new("RGB", (17, 23), color).save(output, format="PNG")
    return output.getvalue()


def _ref(tmp_path, index, role="style"):
    data = _png((index * 20, 0, 0))
    path = tmp_path / f"ref-{index}.png"
    path.write_bytes(data)
    return ReferenceAsset(
        path=path, role=role, entity_id=None, appearance_state_id=None,
        authority_scope=AuthorityScope.CONTEXTUAL, preserve_facets=(), ignore_facets=(),
        pose=None, content_sha256=hashlib.sha256(data).hexdigest(),
        lineage_parent_sha256=None, label=f"authority-{index}",
    )


def _request(config, refs=()):
    return compile_non_panel_request(
        config,
        AbstractStyleProofInput(asset_identity="style:1", prompt=GenerationPromptInput(
            visual_brief="An abstract cobalt arrangement", width=819, height=1024,
        )),
        reference_plan=reference_plan_for_assets(config, list(refs)),
    )


def test_codex_round_trip_binds_prompt_references_and_execution(routed, tmp_path):
    request = _request(routed, [_ref(tmp_path, 1), _ref(tmp_path, 2, "prop")])
    wire = ProviderWireRequest.from_json(request.wire.to_json())
    assert validate_codex_wire(wire) == "gpt-5.6-terra"
    assert [ref.role_label for ref in wire.references] == ["style:authority-1", "prop:authority-2"]
    assert all(ref.instruction in wire.prompt_parts[0] for ref in wire.references)
    for changed in (
        replace(wire, prompt_parts=("Different prompt",)),
        replace(wire, references=tuple(reversed(wire.references))),
        replace(wire, controls=(("reasoning_model", "another-model"),)),
    ):
        with pytest.raises(ProviderWireError):
            validate_codex_wire(changed)
    drifted = replace(wire, configured_provider_model="openai/gpt-image-2")
    drifted = replace(drifted, execution_fingerprint=drifted.recompute_execution_fingerprint())
    with pytest.raises(ProviderWireError):
        validate_codex_wire(drifted)


def test_six_authoritative_refs_fail_before_submission(routed, tmp_path):
    with pytest.raises(ValueError, match="overflow"):
        _request(routed, [_ref(tmp_path, index) for index in range(6)])


def test_transport_preserves_order_bytes_and_unknown_identity(routed, tmp_path, monkeypatch):
    refs = [_ref(tmp_path, 1), _ref(tmp_path, 2, "prop")]
    request = _request(routed, refs)
    output = _png("blue")

    async def generate(**kwargs):
        assert kwargs["references"] == tuple((ref.path.read_bytes(), "image/png") for ref in refs)
        assert kwargs["prompt"] == "\n\n".join(request.wire.prompt_parts)
        return codex_runtime.CodexImageResult(output, 10, 20, {"revised_prompt": "actual tool prompt"})

    monkeypatch.setattr(codex_runtime, "run_image", generate)
    result = asyncio.run(CodexDevImageProvider().generate_wire(
        wire=request.wire, config=routed, event_id="event", metadata={},
    ))
    assert result.image_bytes == output
    assert result.actual_provider_model is None
    assert result.raw_response["codex_runtime"]["revised_prompt"] == "actual tool prompt"
    refs[0].path.write_bytes(_png("red"))
    with pytest.raises(ProviderWireError, match="digest mismatch"):
        asyncio.run(CodexDevImageProvider().generate_wire(
            wire=request.wire, config=routed, event_id="event", metadata={},
        ))


def test_invalid_artifact_retains_usage_evidence(routed, monkeypatch):
    async def generate(**kwargs):
        return codex_runtime.CodexImageResult(b"not an image", 10, 20, {"submitted": True})

    monkeypatch.setattr(codex_runtime, "run_image", generate)
    with pytest.raises(codex_runtime.CodexRuntimeError) as failure:
        asyncio.run(CodexDevImageProvider().generate_wire(
            wire=_request(routed).wire, config=routed, event_id="event", metadata={},
        ))
    assert failure.value.metadata["input_tokens"] == 10
    assert failure.value.metadata["submitted"] is True


@pytest.fixture
def persisted_events(monkeypatch):
    from novel_to_comic.ai import client
    from novel_to_comic.server import db

    rows = {"event": {"status": "started"}}

    class Database:
        def table(self, name):
            assert name == "ai_usage_events"
            return self

        def update(self, values):
            self.values = values
            return self

        def eq(self, field, value):
            assert field == "id"
            self.event_id = value
            return self

        def execute(self):
            rows[self.event_id].update(self.values)

    monkeypatch.setattr(db, "get_db", lambda: Database())
    monkeypatch.setattr(client, "_settle_event_usage", lambda *args, **kwargs: None)
    monkeypatch.setattr(client, "_log_langfuse_generation", lambda **kwargs: None)
    return rows


@pytest.mark.parametrize("write_fails", [False, True])
def test_output_finalization_persists_completed_runtime_evidence(routed, tmp_path, monkeypatch, persisted_events, write_fails):
    import datetime
    import time
    from novel_to_comic.ai import finalisation
    from novel_to_comic.ai.providers.base import ProviderRawResult

    image_bytes = _png("blue")
    evidence = {
        "thread_id": "thread", "turn_id": "turn", "tool_id": "tool",
        "image_status": "completed", "image": codex_runtime.validate_image_bytes(image_bytes),
        "submitted": True, "indeterminate": False,
    }
    def fail_write(*args):
        raise OSError("disk unavailable")

    if write_fails:
        monkeypatch.setattr(finalisation, "_write_image_outputs", fail_write)
    ctx = finalisation.ImageCallContext(
        event_id="event", operation="image", metadata={"funding": "codex_subscription"},
        params={}, estimated_cost_usd=None, started=time.perf_counter(),
        started_at=datetime.datetime.now(datetime.UTC), langfuse_input={},
    )
    output_path = tmp_path.resolve() / "output.png"

    async def finalize():
        return await finalisation.finalise_image_success(
            ctx=ctx, config=routed, model="image-quality", feature="test",
            output_path=output_path,
            raw=ProviderRawResult(image_bytes=image_bytes, raw_response={
                "usage": {"prompt_tokens": 10, "completion_tokens": 20},
                "codex_runtime": evidence,
            }),
        )

    if write_fails:
        with pytest.raises(OSError) as failure:
            asyncio.run(finalize())
        assert failure.value.metadata["completed_result_metadata"] == evidence
        assert failure.value.metadata["completed_result_available"] is True
    else:
        result = asyncio.run(finalize())
        assert result.response_metadata == evidence
        assert output_path.read_bytes() == image_bytes
    event = persisted_events["event"]
    assert (event["status"], event["funding"], event["input_tokens"]) == (
        "failed" if write_fails else "succeeded", "codex_subscription", 10,
    )
    assert event["image_count"] == 1
    assert event["metadata_json"]["codex_runtime"] == evidence
    assert event["cost_usd"] is None


@pytest.mark.parametrize("outcome", ["failed", "cancelled"])
def test_indeterminate_image_failure_persists_runtime_evidence(routed, persisted_events, outcome):
    import datetime
    import time
    from novel_to_comic.ai import finalisation

    evidence = {
        "submitted": True, "indeterminate": True, "thread_id": "thread",
        "turn_id": "turn", "tool_id": "tool", "input_tokens": 31, "output_tokens": 7,
        "references": [{"sha256": "b" * 64, "mime": "image/png", "width": 17, "height": 23}],
        "events": [{"type": "imageGeneration", "id": "tool", "status": "in_progress"}],
    }
    error = codex_runtime.CodexRuntimeError("runtime_timeout", evidence)
    ctx = finalisation.ImageCallContext(
        event_id="event", operation="image", metadata={"funding": "codex_subscription", "stage": "cast"},
        params={}, estimated_cost_usd=None, started=time.perf_counter(),
        started_at=datetime.datetime.now(datetime.UTC), langfuse_input={},
    )
    finalize = finalisation.finalise_image_failure if outcome == "failed" else finalisation.finalise_image_cancelled
    asyncio.run(finalize(ctx=ctx, config=routed, model="image-quality", feature="test", error=error))
    event = persisted_events["event"]
    assert event["status"] == outcome
    assert event["metadata_json"]["codex_runtime"] == evidence
    assert event["metadata_json"]["stage"] == "cast"
    assert event["usage_json"] == {"prompt_tokens": 31, "completion_tokens": 7, "image_count": 0}
    assert event["image_count"] == 0
    assert event["provider_model"] is None
    assert event["cost_usd"] is None


@pytest.mark.parametrize("validated", [True, False])
def test_cancelled_image_checkpoint_counts_only_validated_completed_artifact(routed, persisted_events, validated):
    import datetime
    import time
    from novel_to_comic.ai import finalisation

    image = codex_runtime.validate_image_bytes(_png("blue"))
    if not validated:
        image.pop("sha256")
    completed = {
        "image_status": "completed", "image": image, "tool_id": "tool",
        "input_tokens": 41, "output_tokens": 9,
    }
    evidence = {
        "submitted": True, "indeterminate": True, "process_group_terminated": True,
        "completed_result_available": True, "completed_result_metadata": completed,
    }
    error = asyncio.CancelledError()
    error.metadata = evidence
    ctx = finalisation.ImageCallContext(
        event_id="event", operation="image", metadata={"funding": "codex_subscription"},
        params={}, estimated_cost_usd=None, started=time.perf_counter(),
        started_at=datetime.datetime.now(datetime.UTC), langfuse_input={},
    )
    asyncio.run(finalisation.finalise_image_cancelled(
        ctx=ctx, config=routed, model="image-quality", feature="test", error=error,
    ))
    event = persisted_events["event"]
    assert event["metadata_json"]["codex_runtime"]["completed_result_metadata"] == completed
    assert event["image_count"] == int(validated)
    assert event["usage_json"] == {"prompt_tokens": 41, "completion_tokens": 9, "image_count": int(validated)}
    assert event["cost_usd"] is None

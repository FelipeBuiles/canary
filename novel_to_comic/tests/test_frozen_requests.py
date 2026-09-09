from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from novel_to_comic.provider_wire import (
    PROVIDER_WIRE_DISCRIMINATOR,
    PROVIDER_WIRE_SCHEMA_VERSION,
    ProviderWireReference,
    ProviderWireRequest,
)
from novel_to_comic.usage import ApiResult


def _wire(sources: list[Path], *, prompt: str = "frozen prompt") -> ProviderWireRequest:
    references = []
    for index, source in enumerate(sources):
        data = source.read_bytes()
        references.append(
            ProviderWireReference(
                index=index,
                source_path=str(source),
                content_sha256=hashlib.sha256(data).hexdigest(),
                role="subject",
                role_label=f"subject:Person {index}",
                instruction=f"subject reference {index}",
                provider_binding=str(index),
                entity_id=f"char_{index}",
                appearance_state_id=None,
                authority_scope="full_appearance",
                preserve_facets=("face", "hair"),
                ignore_facets=(),
            )
    )
    request = ProviderWireRequest(
        discriminator=PROVIDER_WIRE_DISCRIMINATOR,
        schema_version=PROVIDER_WIRE_SCHEMA_VERSION,
        requested_alias="image-quality",
        expected_route="balanced",
        provider_key="openai",
        configured_provider_model="gateway/image-quality",
        prompt_parts=(prompt,),
        references=tuple(references),
        width=768,
        height=1024,
        structured_aspect=None,
        controls=(("quality", "medium"),),
        compiled_request_sha256="c" * 64,
        execution_fingerprint="",
    )
    return replace(request, execution_fingerprint=request.recompute_execution_fingerprint())


def _make_app() -> SimpleNamespace:
    return SimpleNamespace(
        state=SimpleNamespace(
            generation_jobs={},
            generation_queue=asyncio.Queue(),
            generation_job_timeout_seconds=30,
        )
    )


@pytest.fixture
def credit_db():
    """Exercise real reservation helpers against a local lease ledger."""
    db = SimpleNamespace(holds={}, reservations=0)

    def rpc(name, params):
        def execute():
            if name == "reserve_stage_credits":
                db.reservations += 1
                hold = str(uuid.uuid4())
                db.holds[hold] = params["p_owner"]
                return SimpleNamespace(data=hold)
            hold = params["p_reservation_id"]
            owned = db.holds.get(hold) == params["p_owner"]
            if name == "check_credit_reservation_lease":
                return SimpleNamespace(data=owned)
            if name == "release_credit_reservation":
                if owned:
                    db.holds.pop(hold)
                return SimpleNamespace(data=None)
            raise AssertionError(f"unexpected billing RPC: {name}")
        return SimpleNamespace(execute=execute)

    db.rpc = rpc
    with patch("novel_to_comic.server.credited_job.get_db", return_value=db):
        try:
            yield db
        finally:
            from novel_to_comic.server.credits import release_reservation

            for hold in tuple(db.holds):
                release_reservation(db, hold)


def test_submission_freezes_wire_and_reference_bytes(tmp_path: Path):
    from novel_to_comic.frozen_requests import (
        load_frozen_request,
        manifest_path,
        submit_frozen_request,
    )

    source = tmp_path / "refs" / "person.png"
    source.parent.mkdir()
    source.write_bytes(b"original-reference")
    wire = _wire([source])

    frozen = submit_frozen_request(
        tmp_path, wire, idempotency_key="draw:scene-1:panel-1"
    )
    source.write_bytes(b"replacement-reference")

    loaded = load_frozen_request(tmp_path, frozen.request_id)
    assert loaded.execution_fingerprint == wire.execution_fingerprint
    assert loaded.wire.prompt_parts == wire.prompt_parts
    assert Path(loaded.wire.references[0].source_path) != source
    assert Path(loaded.wire.references[0].source_path).read_bytes() == b"original-reference"
    assert manifest_path(tmp_path, frozen.request_id).exists()

    raw = json.loads(manifest_path(tmp_path, frozen.request_id).read_text())
    assert raw["manifest_sha256"] == frozen.manifest_sha256
    assert "litellm" not in json.dumps(raw).lower()


def test_frozen_blobs_are_real_files_and_deduplicate_by_digest(tmp_path: Path):
    from novel_to_comic.frozen_requests import submit_frozen_request

    first = tmp_path / "refs" / "first.png"
    second = tmp_path / "refs" / "second.png"
    first.parent.mkdir()
    first.write_bytes(b"same-bytes")
    second.write_bytes(b"same-bytes")

    one = submit_frozen_request(tmp_path, _wire([first]))
    two = submit_frozen_request(tmp_path, _wire([second]))
    first_blob = Path(one.wire.references[0].source_path)
    second_blob = Path(two.wire.references[0].source_path)

    assert first_blob == second_blob
    assert first_blob.is_file()
    assert not first_blob.is_symlink()
    assert first_blob.stat().st_nlink == 1


@pytest.mark.parametrize("shortcut", ["symlink", "hardlink"])
def test_submission_rejects_linked_source(shortcut: str, tmp_path: Path):
    from novel_to_comic.frozen_requests import FrozenRequestIntegrityError, submit_frozen_request

    project_source = tmp_path / "refs" / "person.png"
    project_source.parent.mkdir(parents=True)
    outside_source = tmp_path.parent / f"frozen-source-{os.getpid()}.png"
    outside_source.write_bytes(b"outside-project")
    try:
        if shortcut == "symlink":
            project_source.symlink_to(outside_source)
        else:
            os.link(outside_source, project_source)
        with pytest.raises(FrozenRequestIntegrityError, match="(symlink|linked|hard-linked|project scope)"):
            submit_frozen_request(tmp_path, _wire([project_source]))
    finally:
        outside_source.unlink(missing_ok=True)


def test_existing_digest_collision_is_rejected_without_overwrite(tmp_path: Path):
    from novel_to_comic.frozen_requests import (
        FrozenRequestIntegrityError,
        blob_path,
        manifest_path,
        submit_frozen_request,
    )

    source = tmp_path / "ref.png"
    source.write_bytes(b"expected")
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    destination = blob_path(tmp_path, digest)
    destination.parent.mkdir(parents=True)
    destination.write_bytes(b"collision")

    with pytest.raises(FrozenRequestIntegrityError, match="digest"):
        submit_frozen_request(tmp_path, _wire([source]))
    assert destination.read_bytes() == b"collision"
    assert not list(tmp_path.glob("requests/*/manifest.json"))
    assert not manifest_path(tmp_path, "missing").exists()


def test_symlinked_blob_store_is_rejected_without_external_write(tmp_path: Path):
    from novel_to_comic.frozen_requests import FrozenRequestIntegrityError, submit_frozen_request

    source = tmp_path / "ref.png"
    source.write_bytes(b"expected")
    external = tmp_path / "external"
    external.mkdir()
    (tmp_path / "requests").mkdir()
    (tmp_path / "requests" / "blobs").symlink_to(external, target_is_directory=True)

    with pytest.raises(FrozenRequestIntegrityError, match="symlink"):
        submit_frozen_request(tmp_path, _wire([source]))
    assert list(external.iterdir()) == []


def test_gc_rejects_symlinked_blob_store_without_deleting_external_files(tmp_path: Path):
    from novel_to_comic.frozen_requests import FrozenRequestIntegrityError, gc_unreferenced_blobs

    external = tmp_path / "external"
    external.mkdir()
    victim = external / "victim.dat"
    victim.write_bytes(b"must survive")
    (tmp_path / "requests").mkdir()
    (tmp_path / "requests" / "blobs").symlink_to(external, target_is_directory=True)

    with pytest.raises(FrozenRequestIntegrityError, match="symlink"):
        gc_unreferenced_blobs(tmp_path)
    assert victim.exists()


def test_partial_staging_publishes_no_manifest(tmp_path: Path):
    from novel_to_comic.frozen_requests import FrozenRequestIntegrityError, submit_frozen_request

    first = tmp_path / "first.png"
    second = tmp_path / "second.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    wire = _wire([first, second])
    second.write_bytes(b"changed-before-submit")

    with pytest.raises(FrozenRequestIntegrityError, match="digest"):
        submit_frozen_request(tmp_path, wire)
    assert not list((tmp_path / "requests").glob("*/manifest.json"))


def test_manifest_or_staged_blob_corruption_fails_before_transport(tmp_path: Path):
    from novel_to_comic.frozen_requests import (
        FrozenRequestIntegrityError,
        execute_frozen_request,
        submit_frozen_request,
    )

    source = tmp_path / "ref.png"
    source.write_bytes(b"safe")
    frozen = submit_frozen_request(tmp_path, _wire([source]))
    Path(frozen.wire.references[0].source_path).write_bytes(b"corrupt")
    called = False

    async def fake_generate_wire_image(**kwargs):
        nonlocal called
        called = True
        return ApiResult(value=kwargs["output_path"])

    with patch("novel_to_comic.ai.generate_wire_image", fake_generate_wire_image):
        with pytest.raises(FrozenRequestIntegrityError, match="digest"):
            asyncio.run(
                execute_frozen_request(
                    tmp_path,
                    frozen.request_id,
                    config=MagicMock(),
                    output_path=tmp_path / "out.png",
                )
            )
    assert called is False


def test_frozen_output_rejects_symlinked_parent_without_external_write(tmp_path: Path):
    from novel_to_comic.ai.finalisation import _write_image_outputs

    external = tmp_path / "external"
    external.mkdir()
    (tmp_path / "output").symlink_to(external, target_is_directory=True)

    with pytest.raises(OSError):
        _write_image_outputs(tmp_path / "output" / "page.png", b"image")
    assert not (external / "panel.png").exists()


def test_execution_uploads_the_snapshot_after_original_mutation(tmp_path: Path):
    from novel_to_comic.frozen_requests import execute_frozen_request, submit_frozen_request

    source = tmp_path / "ref.png"
    source.write_bytes(b"original")
    frozen = submit_frozen_request(tmp_path, _wire([source]))
    source.write_bytes(b"changed-after-enqueue")
    seen = {}

    async def fake_generate_wire_image(**kwargs):
        seen.update(kwargs)
        ref_path = Path(kwargs["wire"].references[0].source_path)
        assert ref_path.read_bytes() == b"original"
        assert kwargs["wire"].prompt_parts == ("frozen prompt",)
        return ApiResult(value=kwargs["output_path"])

    with patch("novel_to_comic.ai.generate_wire_image", fake_generate_wire_image):
        result = asyncio.run(
            execute_frozen_request(
                project_dir=tmp_path,
                request_id=frozen.request_id,
                config=MagicMock(image_model="changed-model"),
                output_path=tmp_path / "out.png",
            )
        )

    assert result.value == tmp_path / "out.png"
    assert seen["wire"].execution_fingerprint == frozen.execution_fingerprint


@pytest.mark.parametrize("shortcut", ["symlink", "hardlink"])
def test_frozen_transport_rejects_linked_snapshot(shortcut: str, tmp_path: Path):
    from novel_to_comic.frozen_requests import FrozenRequestIntegrityError, load_frozen_request, submit_frozen_request

    source = tmp_path / "ref.png"
    source.write_bytes(b"original")
    frozen = submit_frozen_request(tmp_path, _wire([source]))
    blob = Path(frozen.wire.references[0].source_path)
    blob.unlink()
    if shortcut == "symlink":
        blob.symlink_to(source)
    else:
        os.link(source, blob)

    with pytest.raises(FrozenRequestIntegrityError, match="(regular|hard-linked|escapes|unreadable)"):
        load_frozen_request(tmp_path, frozen.request_id)


def test_manifest_tampering_fails_closed(tmp_path: Path):
    from novel_to_comic.frozen_requests import (
        FrozenRequestIntegrityError,
        load_frozen_request,
        manifest_path,
        submit_frozen_request,
    )

    source = tmp_path / "ref.png"
    source.write_bytes(b"safe")
    frozen = submit_frozen_request(tmp_path, _wire([source]))
    path = manifest_path(tmp_path, frozen.request_id)
    raw = json.loads(path.read_text())
    raw["wire_request"]["prompt_parts"] = ["tampered"]
    path.write_text(json.dumps(raw))

    with pytest.raises(FrozenRequestIntegrityError, match="manifest"):
        load_frozen_request(tmp_path, frozen.request_id)


def test_same_idempotency_key_is_reused_but_conflicting_request_is_rejected(tmp_path: Path):
    from novel_to_comic.frozen_requests import (
        FrozenRequestIdempotencyConflict,
        submit_frozen_request,
    )

    source = tmp_path / "ref.png"
    source.write_bytes(b"safe")
    one = submit_frozen_request(tmp_path, _wire([source]), idempotency_key="same")
    two = submit_frozen_request(tmp_path, _wire([source]), idempotency_key="same")
    assert two.request_id == one.request_id

    with pytest.raises(FrozenRequestIdempotencyConflict):
        submit_frozen_request(
            tmp_path, _wire([source], prompt="different"), idempotency_key="same"
        )


def test_gc_keeps_referenced_blobs_and_removes_only_orphans(tmp_path: Path):
    from novel_to_comic.frozen_requests import (
        blob_path,
        gc_unreferenced_blobs,
        submit_frozen_request,
    )

    source = tmp_path / "ref.png"
    source.write_bytes(b"referenced")
    frozen = submit_frozen_request(tmp_path, _wire([source]))
    referenced = Path(frozen.wire.references[0].source_path)
    orphan_digest = hashlib.sha256(b"orphan").hexdigest()
    orphan = blob_path(tmp_path, orphan_digest)
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_bytes(b"orphan")

    removed = gc_unreferenced_blobs(tmp_path)
    assert orphan_digest in removed
    assert not orphan.exists()
    assert referenced.exists()


def test_request_ids_are_project_scoped(tmp_path: Path):
    from novel_to_comic.frozen_requests import FrozenRequestNotFound, load_frozen_request, submit_frozen_request

    project_one = tmp_path / "one"
    project_two = tmp_path / "two"
    source = project_one / "ref.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"one")
    frozen = submit_frozen_request(project_one, _wire([source]))

    with pytest.raises(FrozenRequestNotFound):
        load_frozen_request(project_two, frozen.request_id)


def test_symlinked_request_directory_cannot_cross_project_scope(tmp_path: Path):
    from novel_to_comic.frozen_requests import FrozenRequestIntegrityError, load_frozen_request, submit_frozen_request

    project_one = tmp_path / "one"
    project_two = tmp_path / "two"
    source = project_one / "ref.png"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"one")
    frozen = submit_frozen_request(project_one, _wire([source]))
    (project_two / "requests").mkdir(parents=True)
    (project_two / "requests" / frozen.request_id).symlink_to(
        project_one / "requests" / frozen.request_id,
        target_is_directory=True,
    )

    with pytest.raises(FrozenRequestIntegrityError, match="symlink"):
        load_frozen_request(project_two, frozen.request_id)


def test_frozen_job_loads_only_persisted_request(tmp_path: Path, credit_db):
    from novel_to_comic.server.credited_job import enqueue_frozen_generation_job

    app = _make_app()
    source = tmp_path / "ref.png"
    source.write_bytes(b"original")
    wire = _wire([source], prompt="prompt frozen at submission")
    seen = {}

    async def fake_execute(**kwargs):
        seen.update(kwargs)
        return ApiResult(value=kwargs["output_path"])

    with patch("novel_to_comic.server.credited_job.execute_frozen_request", fake_execute):
        job, created = enqueue_frozen_generation_job(
            app,
            project_name="project",
            user_id="user",
            project_id="project-id",
            project_dir=tmp_path,
            config=MagicMock(),
            stage="draw",
            kind="panel_regen",
            label="panel",
            payload={"panel": 1},
            wire=wire,
            output_path=tmp_path / "draw" / "panel.png",
            debit_description="panel",
            idempotency_key="panel-1",
            estimate_credits=5,
            operations=(("image", "image-quality"),),
        )
        source.write_bytes(b"changed-after-submit")
        asyncio.run(job.runner())

    assert created is True
    assert seen["request_id"]
    assert seen["output_path"] == tmp_path / "draw" / "panel.png"
    assert credit_db.reservations == 1
    assert not credit_db.holds


def test_staging_failure_does_not_enqueue_or_debit(tmp_path: Path):
    from novel_to_comic.server.credited_job import enqueue_frozen_generation_job
    from novel_to_comic.frozen_requests import FrozenRequestIntegrityError

    app = _make_app()
    source = tmp_path / "ref.png"
    source.write_bytes(b"original")
    wire = _wire([source])
    source.write_bytes(b"changed-before-submit")

    with patch("novel_to_comic.server.credited_job.debit_model_usage") as debit:
        with pytest.raises(FrozenRequestIntegrityError):
            enqueue_frozen_generation_job(
                app,
                project_name="project",
                user_id="user",
                project_id="project-id",
                project_dir=tmp_path,
                config=MagicMock(),
                stage="draw",
                kind="panel_regen",
                label="panel",
                payload={"panel": 1},
                wire=wire,
                output_path=tmp_path / "draw" / "panel.png",
                debit_description="panel",
                operations=(("image", "image-quality"),),
            )

    assert app.state.generation_queue.empty()
    debit.assert_not_called()


def test_duplicate_frozen_enqueue_is_idempotent_and_not_double_queued(tmp_path: Path, credit_db):
    from novel_to_comic.server.credited_job import enqueue_frozen_generation_job

    app = _make_app()
    source = tmp_path / "ref.png"
    source.write_bytes(b"original")
    kwargs = {
        "project_name": "project",
        "user_id": "user",
        "project_id": "project-id",
        "project_dir": tmp_path,
        "config": MagicMock(),
        "stage": "draw",
        "kind": "panel_regen",
        "label": "panel",
        "payload": {"panel": 1},
        "wire": _wire([source]),
        "output_path": tmp_path / "draw" / "panel.png",
        "debit_description": "panel",
        "idempotency_key": "panel-1",
        "estimate_credits": 5,
        "operations": (("image", "image-quality"),),
    }
    first, first_created = enqueue_frozen_generation_job(app, **kwargs)
    second, second_created = enqueue_frozen_generation_job(app, **kwargs)

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert app.state.generation_queue.qsize() == 1
    assert credit_db.reservations == 1
    assert len(credit_db.holds) == 1


def test_concurrent_frozen_enqueue_is_idempotent(tmp_path: Path, credit_db):
    from novel_to_comic.server.credited_job import enqueue_frozen_generation_job

    app = _make_app()
    source = tmp_path / "ref.png"
    source.write_bytes(b"original")
    kwargs = {
        "project_name": "project",
        "user_id": "user",
        "project_id": "project-id",
        "project_dir": tmp_path,
        "config": MagicMock(),
        "stage": "draw",
        "kind": "panel_regen",
        "label": "panel",
        "payload": {"panel": 1},
        "wire": _wire([source]),
        "output_path": tmp_path / "draw" / "panel.png",
        "debit_description": "panel",
        "idempotency_key": "panel-concurrent",
        "estimate_credits": 5,
        "operations": (("image", "image-quality"),),
    }

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(lambda _index: enqueue_frozen_generation_job(app, **kwargs), range(2))
        )

    assert sum(created for _, created in results) == 1
    assert results[0][0].id == results[1][0].id
    assert app.state.generation_queue.qsize() == 1
    assert credit_db.reservations == 1
    assert len(credit_db.holds) == 1


def test_completed_frozen_enqueue_remains_idempotent(tmp_path: Path, credit_db):
    from novel_to_comic.server.credited_job import enqueue_frozen_generation_job

    app = _make_app()
    source = tmp_path / "ref.png"
    source.write_bytes(b"original")
    kwargs = {
        "project_name": "project",
        "user_id": "user",
        "project_id": "project-id",
        "project_dir": tmp_path,
        "config": MagicMock(),
        "stage": "draw",
        "kind": "panel_regen",
        "label": "panel",
        "payload": {"panel": 1},
        "wire": _wire([source]),
        "output_path": tmp_path / "draw" / "panel.png",
        "debit_description": "panel",
        "idempotency_key": "panel-complete",
        "estimate_credits": 5,
        "operations": (("image", "image-quality"),),
    }

    async def fake_generate_wire_image(**kwargs):
        return ApiResult(value=kwargs["output_path"])

    with patch("novel_to_comic.ai.generate_wire_image", fake_generate_wire_image):
        first, first_created = enqueue_frozen_generation_job(app, **kwargs)
        asyncio.run(first.runner())
        first.status = "complete"
        second, second_created = enqueue_frozen_generation_job(app, **kwargs)

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert app.state.generation_queue.qsize() == 1
    assert credit_db.reservations == 1
    assert not credit_db.holds

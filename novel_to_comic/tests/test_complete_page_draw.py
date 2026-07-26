from __future__ import annotations

import asyncio
import io
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from PIL import Image

from novel_to_comic.config import Config
from novel_to_comic.models.adaptation import LetteringItem
from novel_to_comic.models.draw import (
    BookEdition,
    CompletePageProviderResult,
    PageCapabilityProfile,
    RetryProvenance,
)
from novel_to_comic.models.page import (
    ApprovedVisualReference,
    ApprovedVisualReferenceInventory,
    ComicPage,
    PageContent,
)
from novel_to_comic.page_drawing import (
    ApprovedReferenceFile,
    GoogleVertexCompletePageTransport,
    VertexCompletePageAdapter,
    compile_page_generation_request,
    draw_complete_page,
    enqueue_complete_page_draw,
    production_page_capability_profile,
    select_book_edition,
)
from novel_to_comic.server.credited_job import enqueue_reserved_generation_job
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


def _profile(**updates: object) -> PageCapabilityProfile:
    payload: dict[str, object] = {
        "id": "nano-banana-pro-complete-page-v1",
        "provider": "vertex-multimodal",
        "model": "gemini-3-pro-image-preview",
        "max_image_references": 4,
        "reference_ordering": "ordered",
        "editing_modes": ["instructed", "region_targeted"],
        "output_width": 2048,
        "output_height": 3072,
        "max_prompt_characters": 32_000,
        "retry_semantics": "idempotent_request",
        "price_per_page_usd": "0.30",
    }
    payload.update(updates)
    return PageCapabilityProfile(**payload)


def _edition(profile: PageCapabilityProfile | None = None) -> BookEdition:
    return BookEdition(
        revision=1,
        id="edition-001",
        capability_profile=profile or _profile(),
    )


def _page(*, revision: int = 2, visual_intent: str = "Ward sees the idol.") -> ComicPage:
    return ComicPage(
        revision=revision,
        page_number=7,
        adaptation_revision=3,
        adaptation_sha256="a" * 64,
        page_turn_role="reveal",
        spread_role="right",
        emphasis="peak",
        density_intent="standard",
        rhythm_intent="A held reveal followed by stunned silence.",
        layout_intent="Three semantic moments, descending into a wide final image.",
        content=[
            PageContent(
                id="content-1",
                order=1,
                beat_ids=["beat-1"],
                visual_intent=visual_intent,
                lettering=[
                    LetteringItem(
                        id="letter-1",
                        kind="caption",
                        text="It was the same face.",
                        source_unit_ids=["source-1"],
                    )
                ],
                entity_ids=["ward", "idol"],
                appearance_state_ids=["ward-bloodied"],
            )
        ],
        reading_order=["content-1", "letter-1"],
    )


def _inventory() -> ApprovedVisualReferenceInventory:
    return ApprovedVisualReferenceInventory(
        references=[
            ApprovedVisualReference(
                id="ward-clean-ref",
                entity_id="ward",
                visual_anchor="Ward clean and uninjured",
            ),
            ApprovedVisualReference(
                id="ward-bloodied-ref",
                entity_id="ward",
                appearance_state_id="ward-bloodied",
                visual_anchor="Ward’s torn left sleeve; blood below the right eye",
            ),
            ApprovedVisualReference(
                id="idol-ref",
                entity_id="idol",
                visual_anchor="green-black stone; exact seven-pointed crown",
            ),
            ApprovedVisualReference(
                id="unused-diagnostic-ref",
                entity_id="unused",
                visual_anchor="must never enter page seven",
            ),
        ]
    )


def _reference_files(tmp_path: Path, *, ward_bytes: bytes = b"ward-v1") -> dict[str, ApprovedReferenceFile]:
    paths = {
        "ward-clean-ref": tmp_path / "ward-clean.png",
        "ward-bloodied-ref": tmp_path / "ward-bloodied.png",
        "idol-ref": tmp_path / "idol.png",
        "unused-diagnostic-ref": tmp_path / "unused.png",
    }
    payloads = {
        "ward-clean-ref": b"unused-clean",
        "ward-bloodied-ref": ward_bytes,
        "idol-ref": b"idol-v1",
        "unused-diagnostic-ref": b"diagnostic-v1",
    }
    for reference_id, path in paths.items():
        path.write_bytes(payloads[reference_id])
    return {
        reference_id: ApprovedReferenceFile(
            reference_id=reference_id,
            path=path,
            media_type="image/png",
        )
        for reference_id, path in paths.items()
    }


def _compile(
    tmp_path: Path,
    *,
    page: ComicPage | None = None,
    files: dict[str, ApprovedReferenceFile] | None = None,
):
    return compile_page_generation_request(
        page or _page(),
        _edition(),
        _inventory(),
        files or _reference_files(tmp_path),
        retry=RetryProvenance(attempt=1),
    )


def test_compiler_freezes_exact_page_authority_and_selected_reference_order(
    tmp_path: Path,
) -> None:
    prepared = _compile(tmp_path)
    request = prepared.request

    assert request.lettering == _page().content[0].lettering
    assert [reference.id for reference in request.references] == [
        "ward-bloodied-ref",
        "idol-ref",
    ]
    assert prepared.reference_bytes == (b"ward-v1", b"idol-v1")
    assert [reference.visual_anchor for reference in request.references] == [
        "Ward’s torn left sleeve; blood below the right eye",
        "green-black stone; exact seven-pointed crown",
    ]
    assert request.comic_page_revision == 2
    assert request.comic_page_sha256 == _page().content_sha256
    assert request.edition_id == "edition-001"
    assert request.edition_sha256 == _edition().content_sha256
    assert request.profile_id == _profile().id
    assert request.model == _profile().model
    assert request.output_width == 2048
    assert request.output_height == 3072
    assert request.output_media_type == "image/png"
    assert request.retry == RetryProvenance(attempt=1)
    assert "It was the same face." in request.prompt
    assert "Ward’s torn left sleeve; blood below the right eye" in request.prompt


def test_production_profile_estimates_page_and_selected_reference_cost(
    tmp_path: Path,
) -> None:
    profile = production_page_capability_profile()
    compiled = compile_page_generation_request(
        _page(),
        _edition(profile),
        _inventory(),
        _reference_files(tmp_path),
        retry=RetryProvenance(attempt=1),
    )

    assert profile.provider == "vertex-multimodal"
    assert profile.model == "gemini-3-pro-image-preview"
    assert compiled.request.estimated_cost_usd == Decimal("0.13624")


def test_request_identity_tracks_page_revision_and_selected_reference_bytes(
    tmp_path: Path,
) -> None:
    original = _compile(tmp_path)
    changed_page = _compile(
        tmp_path,
        page=_page(revision=3, visual_intent="Ward recoils from the idol."),
    )
    changed_files = _reference_files(tmp_path, ward_bytes=b"ward-v2")
    changed_reference = _compile(tmp_path, files=changed_files)

    assert changed_page.request.request_sha256 != original.request.request_sha256
    assert changed_reference.request.request_sha256 != original.request.request_sha256


def test_request_identity_records_retry_lineage(tmp_path: Path) -> None:
    original = _compile(tmp_path)
    retried = compile_page_generation_request(
        _page(),
        _edition(),
        _inventory(),
        _reference_files(tmp_path),
        retry=RetryProvenance(
            attempt=2,
            retries_request_sha256=original.request.request_sha256,
        ),
    )

    assert retried.request.retry.retries_request_sha256 == (
        original.request.request_sha256
    )
    assert retried.request.request_sha256 != original.request.request_sha256

    with pytest.raises(ValueError, match="retry attempt"):
        compile_page_generation_request(
            _page(),
            _edition(_profile(max_attempts=1)),
            _inventory(),
            _reference_files(tmp_path),
            retry=RetryProvenance(
                attempt=2,
                retries_request_sha256=original.request.request_sha256,
            ),
        )


def test_unselected_reference_diagnostics_do_not_change_request_identity(
    tmp_path: Path,
) -> None:
    files = _reference_files(tmp_path)
    original = _compile(tmp_path, files=files)
    files["unused-diagnostic-ref"].path.write_bytes(b"changed diagnostic bytes")
    changed = _compile(tmp_path, files=files)

    assert changed.request.request_sha256 == original.request.request_sha256


def test_book_edition_rejects_non_production_capability_before_cost() -> None:
    with pytest.raises(ValueError, match="complete-page production"):
        select_book_edition(
            edition_id="edition-001",
            profile=_profile(provider="reve"),
        )

    existing = _edition()
    with pytest.raises(ValueError, match="fixed"):
        select_book_edition(
            edition_id=existing.id,
            profile=_profile(model="another-model"),
            existing=existing,
        )


def test_reference_capacity_fails_during_compilation(tmp_path: Path) -> None:
    edition = _edition(_profile(max_image_references=1))

    with pytest.raises(ValueError, match="reference count"):
        compile_page_generation_request(
            _page(),
            edition,
            _inventory(),
            _reference_files(tmp_path),
            retry=RetryProvenance(attempt=1),
        )


class _RecordingTransport:
    def __init__(self, result: CompletePageProviderResult) -> None:
        self.result = result
        self.submitted = []

    async def generate(self, request):
        self.submitted.append(request)
        return self.result


def _provider_result() -> CompletePageProviderResult:
    return CompletePageProviderResult(
        artifact_kind="complete_page",
        image_bytes=b"complete-page-png",
        media_type="image/png",
        width=2048,
        height=3072,
        latency_ms=321,
        provider_request_id="vertex-request-1",
        actual_provider_model="vertex_ai/gemini-3-pro-image-preview",
        usage=UsageRecord(
            provider="gemini",
            model="gemini-3-pro-image-preview",
            provider_model="vertex_ai/gemini-3-pro-image-preview",
            operation="image",
            image_count=1,
            cost_usd=0.30,
            cost_source="provider",
        ),
    )


def test_vertex_adapter_submits_exactly_the_prepared_complete_page_request(
    tmp_path: Path,
) -> None:
    compiled = _compile(tmp_path)
    transport = _RecordingTransport(_provider_result())
    adapter = VertexCompletePageAdapter(transport)
    prepared = adapter.prepare(compiled)

    result = asyncio.run(adapter.generate(prepared))

    assert transport.submitted == [prepared]
    assert result.artifact_kind == "complete_page"
    assert result.image_bytes == b"complete-page-png"
    assert not hasattr(result, "panel_number")

    wrong_model = _provider_result().model_copy(
        update={"actual_provider_model": "vertex_ai/another-model"}
    )
    rejecting_adapter = VertexCompletePageAdapter(_RecordingTransport(wrong_model))
    with pytest.raises(ValueError, match="fixed complete-page profile"):
        asyncio.run(rejecting_adapter.generate(rejecting_adapter.prepare(compiled)))


def test_native_vertex_transport_preserves_reference_order_and_returns_one_page(
    tmp_path: Path,
) -> None:
    compiled = compile_page_generation_request(
        _page(),
        _edition(_profile(output_width=8, output_height=12)),
        _inventory(),
        _reference_files(tmp_path),
        retry=RetryProvenance(attempt=1),
    )
    prepared = VertexCompletePageAdapter(
        _RecordingTransport(_provider_result())
    ).prepare(compiled)
    output = io.BytesIO()
    Image.new("RGB", (8, 12), "black").save(output, format="PNG")
    response = httpx.Response(
        200,
        json={
            "id": "vertex-response-1",
            "model": "vertex_ai/gemini-3-pro-image-preview",
            "data": [{"b64_json": "unused-by-test-decoder"}],
        },
        request=httpx.Request("POST", "http://gateway/v1/images/edits"),
    )
    usage = UsageRecord(
        provider="gemini",
        model=prepared.model,
        operation="image",
        image_count=1,
        cost_usd=0.30,
        cost_source="provider",
    )
    post = AsyncMock(return_value=response)
    with (
        patch("novel_to_comic.ai.client._base_url", return_value="http://gateway"),
        patch("novel_to_comic.ai.client._headers", return_value={}),
        patch("novel_to_comic.ai.client._post_with_retry", post),
        patch(
            "novel_to_comic.ai.client._decode_image_response",
            AsyncMock(return_value=output.getvalue()),
        ),
        patch("novel_to_comic.ai.client._extract_usage", return_value=usage),
    ):
        transport = GoogleVertexCompletePageTransport(
            Config(google_cloud_project="test-project"),
        )
        result = asyncio.run(transport.generate(prepared))

    submitted = post.call_args.kwargs
    frozen = submitted["data"]["canary_complete_page_request"]
    assert frozen == prepared.frozen_request_json
    assert [item[1][1] for item in submitted["files"]] == list(
        prepared.reference_bytes
    )
    assert submitted["data"]["prompt"] == prepared.prompt
    assert result.artifact_kind == "complete_page"
    assert (result.width, result.height) == (8, 12)


def test_draw_persists_immutable_request_render_usage_cost_and_lineage(
    tmp_path: Path,
) -> None:
    compiled = _compile(tmp_path)
    adapter = VertexCompletePageAdapter(_RecordingTransport(_provider_result()))
    artifacts = TargetArtifacts(tmp_path / "project")

    result = asyncio.run(
        draw_complete_page(
            compiled,
            adapter=adapter,
            artifacts=artifacts,
            request_revision=1,
            render_revision=1,
        )
    )

    assert artifacts.read_request(7, 1) == compiled.request
    assert artifacts.read_render(7, 1) == b"complete-page-png"
    assert artifacts.read_provenance(7, 1) == result
    assert result.render.request_sha256 == compiled.request.request_sha256
    assert result.render.comic_page_revision == 2
    assert result.render.latency_ms == 321
    assert result.render.cost_usd == Decimal("0.3")
    assert result.usage.cost_usd == 0.30
    assert result.usage.image_count == 1

    with pytest.raises(ValueError, match="immutable"):
        artifacts.write_render(
            page_number=7,
            render_revision=1,
            image=b"different",
        )


def _make_app() -> MagicMock:
    app = MagicMock()
    app.state.generation_jobs = {}
    app.state.generation_queue = asyncio.Queue()
    return app


def test_reserved_generation_job_reserves_executes_debits_and_releases(
    tmp_path: Path,
) -> None:
    app = _make_app()
    usage = _provider_result().usage

    async def work() -> ApiResult[str]:
        return ApiResult(value="done", usage=usage)

    with (
        patch("novel_to_comic.server.credited_job.get_db", return_value=object()),
        patch(
            "novel_to_comic.server.credited_job.reserve_credits",
            return_value=("reservation-1", "ledger-job-1"),
        ) as reserve,
        patch("novel_to_comic.server.credited_job.release_reservation") as release,
        patch("novel_to_comic.server.credited_job.debit_model_usage") as debit,
        patch("novel_to_comic.server.credited_job.ai_request_context"),
    ):
        job, created = enqueue_reserved_generation_job(
            app,
            project_name="project",
            user_id="user-1",
            project_id="project-1",
            project_dir=tmp_path,
            stage="draw",
            kind="complete_page_draw",
            label="Page 7",
            payload={"request_sha256": "f" * 64},
            work=work,
            debit_description="Complete page 7",
            reservation_credits=38,
        )
        asyncio.run(job.runner())

    assert created is True
    reserve.assert_called_once()
    debit.assert_called_once()
    release.assert_called_once()


def test_complete_page_enqueue_uses_credited_lifecycle_and_persists_result(
    tmp_path: Path,
) -> None:
    app = _make_app()
    compiled = _compile(tmp_path)
    artifacts = TargetArtifacts(tmp_path / "project")
    adapter = VertexCompletePageAdapter(_RecordingTransport(_provider_result()))

    with (
        patch("novel_to_comic.server.credited_job.get_db", return_value=object()),
        patch(
            "novel_to_comic.server.credited_job.reserve_credits",
            return_value=("reservation-1", "ledger-job-1"),
        ) as reserve,
        patch("novel_to_comic.server.credited_job.release_reservation") as release,
        patch("novel_to_comic.server.credited_job.debit_model_usage") as debit,
        patch("novel_to_comic.server.credited_job.ai_request_context"),
    ):
        job, created = enqueue_complete_page_draw(
            app,
            project_name="project",
            user_id="user-1",
            project_id="project-1",
            project_dir=tmp_path / "project",
            compiled=compiled,
            adapter=adapter,
            artifacts=artifacts,
            request_revision=1,
            render_revision=1,
        )
        asyncio.run(job.runner())

    assert created is True
    assert reserve.call_args.args[-1] == 38
    debit.assert_called_once()
    release.assert_called_once()
    assert artifacts.read_render(7, 1) == b"complete-page-png"


def test_reserved_generation_job_releases_without_debit_on_cancellation(
    tmp_path: Path,
) -> None:
    app = _make_app()

    async def work() -> ApiResult[str]:
        raise asyncio.CancelledError

    with (
        patch("novel_to_comic.server.credited_job.get_db", return_value=object()),
        patch(
            "novel_to_comic.server.credited_job.reserve_credits",
            return_value=("reservation-1", "ledger-job-1"),
        ),
        patch("novel_to_comic.server.credited_job.release_reservation") as release,
        patch("novel_to_comic.server.credited_job.debit_model_usage") as debit,
        patch("novel_to_comic.server.credited_job.ai_request_context"),
    ):
        job, _ = enqueue_reserved_generation_job(
            app,
            project_name="project",
            user_id="user-1",
            project_id="project-1",
            project_dir=tmp_path,
            stage="draw",
            kind="complete_page_draw",
            label="Page 7",
            payload={"request_sha256": "f" * 64},
            work=work,
            debit_description="Complete page 7",
            reservation_credits=38,
        )
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(job.runner())

    debit.assert_not_called()
    release.assert_called_once()

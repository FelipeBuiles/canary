from __future__ import annotations

import asyncio
import hashlib
import io
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from PIL import Image

from novel_to_comic.ai.errors import AITransportError
from novel_to_comic.config import Config
from novel_to_comic.models.adaptation import LetteringItem
from novel_to_comic.models.draw import (
    OCRExtraction,
    OCRTextObservation,
    PageRenderCorrection,
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
    analyze_complete_page,
    GoogleVertexCompletePageTransport,
    VertexCompletePageAdapter,
    compile_page_generation_request,
    draw_complete_page,
    ensure_current_page_edition,
    enqueue_complete_page_draw,
    production_page_capability_profile,
    select_book_edition,
)
from novel_to_comic.server.routers.pages import _aggregated_correction_retry, _generation_retry
from novel_to_comic.server.credited_job import enqueue_reserved_generation_job
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord


def _profile(**updates: object) -> PageCapabilityProfile:
    payload: dict[str, object] = production_page_capability_profile().model_dump()
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
                        delivery="narration",
                        source_unit_ids=["source-1"],
                    )
                ],
                entity_ids=["ward", "idol"],
                appearance_states={"ward": "ward-bloodied"},
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


def _provider_brief(prompt: str) -> dict:
    return json.JSONDecoder().raw_decode(prompt[prompt.index("{"):])[0]


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
    assert request.output_width == 1696
    assert request.output_height == 2528
    assert request.output_media_type == "image/png"
    assert request.retry == RetryProvenance(attempt=1)
    assert "It was the same face." in request.prompt
    assert "Ward’s torn left sleeve; blood below the right eye" in request.prompt
    assert "ward-bloodied" not in request.prompt
    assert "idol-ref" not in request.prompt


def test_provider_subject_binding_separates_identity_from_state_and_speaker_name(tmp_path: Path) -> None:
    inventory = _inventory().model_copy(update={"references": tuple(
        ref.model_copy(update={"label": "Ward — bloodied" if ref.appearance_state_id else "Ward"})
        for ref in _inventory().references
    )})
    bindings = []
    for state_first in (True, False):
        page = _ordered_page(state_first=state_first)
        stated = next(item for item in page.content if item.appearance_states)
        lettering = tuple(
            LetteringItem(
                id=f"spoken-{entity}", kind="dialogue", text="Stay.",
                speaker="Ward", speaker_entity_id=entity, delivery="onscreen",
                source_unit_ids=["source-1"],
            )
            for entity in ("ward", "idol")
        )
        stated = stated.model_copy(update={
            "lettering": lettering,
        })
        page = page.model_copy(update={
            "content": tuple(stated if item.appearance_states else item for item in page.content),
            "layout_intent": "ward is already inside; the arrival is complete.",
            "reading_order": (*[item.id for item in page.content], *[item.id for item in lettering]),
        })
        request = compile_page_generation_request(
            page, _edition(), inventory, _reference_files(tmp_path),
            retry=RetryProvenance(attempt=1),
        ).request
        brief = _provider_brief(request.prompt)
        refs = {ref["image"]: ref for ref in brief["approved_page_references"]}
        by_appearance = {ref["appearance"]: ref["subject"] for ref in refs.values()}
        assert by_appearance["Ward — bloodied"] in {
            subject["subject"] for panel in brief["canonical_comic_page"]["content"]
            for subject in panel["visible_subjects"]
        }
        ward_handles = []
        for panel, canonical in zip(brief["canonical_comic_page"]["content"], page.content, strict=True):
            ward = next(subject for subject in panel["visible_subjects"]
                        if refs[subject["references"][0]["image"]]["visual_anchor"].startswith("Ward"))
            ward_handles.append(ward["subject"])
            expected = "Ward — bloodied" if canonical.appearance_states else "Ward"
            assert refs[ward["references"][0]["image"]]["appearance"] == expected
        assert ward_handles[0] == ward_handles[1]
        speakers = next(panel["lettering"] for panel in brief["exact_lettering"]["panels"] if panel["lettering"])
        assert speakers[0]["speaker"] == speakers[1]["speaker"]
        assert speakers[0]["speaker_entity_id"] != speakers[1]["speaker_entity_id"]
        assert speakers[0]["speaker_entity_id"] == ward_handles[0]
        assert [item["text"] for item in speakers] == ["Stay.", "Stay."]
        assert brief["canonical_staging_and_layout"] == (
            f"{ward_handles[0]} is already inside; the arrival is complete."
        )
        assert "page_number" not in brief["canonical_comic_page"]
        assert request.comic_page_sha256 not in request.prompt
        assert all(ref.id not in request.prompt for ref in request.references)
        bindings.append(ward_handles[0])
    assert bindings[0] == bindings[1]


def test_compiler_freezes_selected_lettering_and_framing_style_across_pages(
    tmp_path: Path,
) -> None:
    style = (
        "Woodcut chiaroscuro.\n\n"
        "LETTERING STANDARD — Preserve exact capitalization; one condensed sans "
        "typeface, black on ivory balloons and captions.\n"
        "PAGE FRAMING STANDARD — Fixed cream outer margin on every page; straight "
        "black borders and uniform gutters; never full bleed."
    )

    styled = compile_page_generation_request(
        _page(),
        _edition(),
        _inventory(),
        _reference_files(tmp_path),
        retry=RetryProvenance(attempt=1),
        style_template=style,
    )
    unstyled = _compile(tmp_path)

    assert _provider_brief(styled.request.prompt)["project_style_direction"] == style
    assert styled.request.request_sha256 != unstyled.request.request_sha256


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
    assert profile.model == "gemini-3-pro-image"
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

    later = compile_page_generation_request(
        _page(),
        _edition(),
        _inventory(),
        _reference_files(tmp_path),
        retry=RetryProvenance(
            attempt=4,
            retries_request_sha256=retried.request.request_sha256,
        ),
    )
    prepared = VertexCompletePageAdapter(_RecordingTransport(_provider_result())).prepare(later)
    assert prepared.request_sha256 == later.request.request_sha256
    assert later.request.retry.attempt > _edition().capability_profile.max_attempts


def test_failed_generation_retry_advances_request_lineage(tmp_path: Path) -> None:
    original = _compile(tmp_path)
    artifacts = TargetArtifacts(tmp_path / "project")
    artifacts.write_request(original.request, request_revision=1)

    retry = _generation_retry(artifacts, page_number=7)
    retried = compile_page_generation_request(
        _page(),
        _edition(),
        _inventory(),
        _reference_files(tmp_path),
        retry=retry,
    )

    assert retry == RetryProvenance(
        attempt=2,
        retries_request_sha256=original.request.request_sha256,
    )
    assert retried.request.request_sha256 != original.request.request_sha256


def test_less_graphic_depiction_preserves_authority_and_softens_visual_treatment(
    tmp_path: Path,
) -> None:
    compiled = compile_page_generation_request(
        _page(),
        _edition(),
        _inventory(),
        _reference_files(tmp_path),
        retry=RetryProvenance(attempt=1),
        depiction="less_graphic",
    )

    assert len(compiled.request.references) == 2
    assert len(compiled.reference_bytes) == 2
    assert "It was the same face." in compiled.request.prompt
    assert "Ward’s torn left sleeve; blood below the right eye" in compiled.request.prompt


def test_edition_rejects_changes_to_current_profile_after_the_model_changes(tmp_path: Path) -> None:
    artifacts = TargetArtifacts(tmp_path)
    old = _edition(_profile(model="old-model"))
    artifacts.write_book_edition(old)
    with pytest.raises(ValueError):
        ensure_current_page_edition(artifacts, old)
    assert artifacts.read_book_edition() == old


def test_edition_rejects_changes_after_current_model_was_saved_with_wrong_dimensions(tmp_path: Path) -> None:
    artifacts = TargetArtifacts(tmp_path)
    old = _edition(_profile(output_width=2048, output_height=3072))
    artifacts.write_book_edition(old)
    with pytest.raises(ValueError):
        ensure_current_page_edition(artifacts, old)
    assert artifacts.read_book_edition() == old


def test_failed_request_gets_its_own_revision_before_render_retry(
    tmp_path: Path,
) -> None:
    compiled = _compile(tmp_path)
    artifacts = TargetArtifacts(tmp_path / "project")
    artifacts.write_request(compiled.request, request_revision=1)

    asyncio.run(
        draw_complete_page(
            compiled,
            adapter=VertexCompletePageAdapter(
                _RecordingTransport(_provider_result())
            ),
            artifacts=artifacts,
            page=_page(),
        )
    )

    assert artifacts.request_revisions(7) == (1, 2)
    assert artifacts.provenance_revisions(7) == (1,)


def test_unselected_reference_diagnostics_do_not_change_request_identity(
    tmp_path: Path,
) -> None:
    files = _reference_files(tmp_path)
    original = _compile(tmp_path, files=files)
    files["unused-diagnostic-ref"].path.write_bytes(b"changed diagnostic bytes")
    changed = _compile(tmp_path, files=files)

    assert changed.request.request_sha256 == original.request.request_sha256


def test_book_edition_rejects_unselected_capability_before_cost() -> None:
    with pytest.raises(ValueError):
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


def test_page_correction_uses_current_model_after_edition_rejects_changes(tmp_path: Path) -> None:
    artifacts = TargetArtifacts(tmp_path)
    old = _edition(_profile(model="gemini-3.1-flash-image"))
    artifacts.write_book_edition(old)
    with pytest.raises(ValueError):
        ensure_current_page_edition(artifacts, old)
    assert artifacts.read_book_edition() == old


def test_reference_capacity_fails_before_generation_instead_of_dropping_identity(tmp_path: Path, monkeypatch) -> None:
    profile = _profile(max_image_references=1)
    monkeypatch.setattr("novel_to_comic.page_drawing.current_page_capability_profile", lambda: profile)
    with pytest.raises(ValueError):
        compile_page_generation_request(_page(), _edition(profile), _inventory(), _reference_files(tmp_path), retry=RetryProvenance(attempt=1))


def test_canonical_page_keeps_overflow_authorities_in_prompt(
    tmp_path: Path,
) -> None:
    extra_entities = [f"extra_{index}" for index in range(1, 8)]
    base_page = _page()
    page = base_page.model_copy(
        update={
            "content": (
                base_page.content[0].model_copy(
                    update={"entity_ids": ["ward", "idol", *extra_entities]}
                ),
            )
        }
    )
    references = list(_inventory().references)
    files = _reference_files(tmp_path)
    for index, entity_id in enumerate(extra_entities, start=1):
        reference_id = f"{entity_id}-ref"
        references.append(
            ApprovedVisualReference(
                id=reference_id,
                entity_id=entity_id,
                visual_anchor=f"extra anchor {index}",
            )
        )
        path = tmp_path / f"{entity_id}.png"
        path.write_bytes(f"extra-{index}".encode())
        files[reference_id] = ApprovedReferenceFile(
            reference_id=reference_id,
            path=path,
            media_type="image/png",
        )

    with pytest.raises(ValueError, match="requires 9 approved references"):
        compile_page_generation_request(
            page,
            _edition(_profile(max_image_references=8)),
            ApprovedVisualReferenceInventory(references=references),
            files,
            retry=RetryProvenance(attempt=1),
        )


def _provider_result() -> CompletePageProviderResult:
    return CompletePageProviderResult(
        artifact_kind="complete_page",
        image_bytes=b"complete-page-png",
        media_type="image/png",
        width=1696,
        height=2528,
        latency_ms=321,
        provider_request_id="vertex-request-1",
        actual_provider_model="vertex_ai/gemini-3-pro-image",
        usage=UsageRecord(
            provider="gemini",
            model="gemini-3-pro-image",
            provider_model="vertex_ai/gemini-3-pro-image",
            operation="image",
            image_count=1,
            cost_usd=0.134,
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
    with pytest.raises(
        ValueError,
        match=(
            "fixed complete-page profile: "
            "model expected=gemini-3-pro-image actual=vertex_ai/another-model"
        ),
    ):
        asyncio.run(rejecting_adapter.generate(rejecting_adapter.prepare(compiled)))

    wrong_dimensions = _provider_result().model_copy(
        update={"width": 2048, "height": 3072}
    )
    rejecting_adapter = VertexCompletePageAdapter(
        _RecordingTransport(wrong_dimensions)
    )
    with pytest.raises(
        ValueError,
        match="dimensions expected=1696x2528 actual=2048x3072",
    ):
        asyncio.run(rejecting_adapter.generate(rejecting_adapter.prepare(compiled)))


def test_native_vertex_transport_preserves_reference_order_and_returns_one_page(
    tmp_path: Path,
) -> None:
    compiled = compile_page_generation_request(
        _page(),
        _edition(),
        _inventory(),
        _reference_files(tmp_path),
        retry=RetryProvenance(attempt=1),
    )
    prepared = VertexCompletePageAdapter(
        _RecordingTransport(_provider_result())
    ).prepare(compiled)
    output = io.BytesIO()
    Image.new("RGB", (1696, 2528), "black").save(output, format="PNG")
    response = httpx.Response(
        200,
        json={
            "id": "vertex-response-1",
            "model": "image-balanced",
            "data": [{"b64_json": "unused-by-test-decoder"}],
        },
        request=httpx.Request("POST", "http://gateway/v1/images/edits"),
    )
    usage = UsageRecord(
        provider="gemini",
        model=prepared.model,
        operation="image",
        image_count=1,
        cost_usd=0.134,
        cost_source="provider",
    )
    post = AsyncMock(return_value=response)
    finalize = MagicMock()
    with (
        patch("novel_to_comic.ai.client._base_url", return_value="http://gateway"),
        patch("novel_to_comic.ai.client._headers", return_value={}),
        patch("novel_to_comic.ai.client._post_with_retry", post),
        patch(
            "novel_to_comic.ai.client._decode_image_response",
            AsyncMock(return_value=output.getvalue()),
        ),
        patch("novel_to_comic.ai.client._extract_usage", return_value=usage),
        patch("novel_to_comic.ai.client._finalize_event", finalize),
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
    assert submitted["data"]["model"] == "image-balanced"
    assert result.artifact_kind == "complete_page"
    assert (result.width, result.height) == (1696, 2528)
    assert result.actual_provider_model == "vertex_ai/gemini-3-pro-image"
    finalized = finalize.call_args.kwargs
    assert finalized["model_alias"] == "image-balanced"
    assert finalized["operation"] == "image"
    assert finalized["metadata"]["trace_name"] == "complete_page_draw"
    assert finalized["langfuse_input"]["prompt"] == prepared.prompt
    assert finalized["langfuse_output"]["actual_provider_model"] == (
        "vertex_ai/gemini-3-pro-image"
    )


def test_native_vertex_transport_uses_generation_endpoint_without_references(
    tmp_path: Path,
) -> None:
    page = _page()
    page = page.model_copy(update={"content": (page.content[0].model_copy(update={
        "entity_ids": (), "appearance_states": {},
    }),)})
    compiled = compile_page_generation_request(
        page, _edition(), ApprovedVisualReferenceInventory(references=[]), {},
        retry=RetryProvenance(attempt=1),
    )
    prepared = VertexCompletePageAdapter(
        _RecordingTransport(_provider_result())
    ).prepare(compiled)
    output = io.BytesIO()
    Image.new("RGB", (1696, 2528), "black").save(output, format="PNG")
    response = httpx.Response(
        200,
        json={
            "id": "vertex-response-1",
            "model": "image-balanced",
            "data": [{"b64_json": "unused-by-test-decoder"}],
        },
        request=httpx.Request("POST", "http://gateway/v1/images/generations"),
    )
    usage = UsageRecord(
        provider="gemini",
        model=prepared.model,
        operation="image",
        image_count=1,
        cost_usd=0.134,
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

    assert post.call_args.args[0] == "http://gateway/v1/images/generations"
    submitted = post.call_args.kwargs
    assert submitted["json"]["model"] == "image-balanced"
    assert submitted["json"]["prompt"] == prepared.prompt
    assert "files" not in submitted
    assert result.actual_provider_model == "vertex_ai/gemini-3-pro-image"


def test_native_vertex_transport_surfaces_provider_error_detail(
    tmp_path: Path,
) -> None:
    prepared = VertexCompletePageAdapter(
        _RecordingTransport(_provider_result())
    ).prepare(_compile(tmp_path))
    response = httpx.Response(
        404,
        json={
            "error": {
                "message": (
                    "Publisher model gemini-3-pro-image was not found "
                    "or this project does not have access."
                )
            }
        },
        request=httpx.Request("POST", "http://gateway/v1/images/edits"),
    )
    with (
        patch("novel_to_comic.ai.client._base_url", return_value="http://gateway"),
        patch("novel_to_comic.ai.client._headers", return_value={}),
        patch(
            "novel_to_comic.ai.client._post_with_retry",
            AsyncMock(return_value=response),
        ),
    ):
        with pytest.raises(
            AITransportError,
            match="does not have access",
        ):
            asyncio.run(
                GoogleVertexCompletePageTransport(Config()).generate(prepared)
            )


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
            page=_page(),
        )
    )

    assert artifacts.read_request(7, 1) == compiled.request
    assert artifacts.read_render(7, 1) == b"complete-page-png"
    assert artifacts.read_provenance(7, 1) == result
    assert result.render.request_sha256 == compiled.request.request_sha256
    assert result.render.comic_page_revision == 2
    assert result.render.latency_ms == 321
    assert result.render.cost_usd == Decimal("0.134")
    assert result.usage.cost_usd == 0.134
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
        patch("novel_to_comic.server.credited_job.assert_reservation_active"),
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
            operations=(("complete_page", "image-balanced"),),
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
        patch("novel_to_comic.server.credited_job.assert_reservation_active"),
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
            config=Config(),
            compiled=compiled,
            adapter=adapter,
            artifacts=artifacts,
            page=_page(),
        )
        asyncio.run(job.runner())

    assert created is True
    assert reserve.call_args.args[-1] == 18
    debit.assert_called_once()
    release.assert_called_once()
    assert artifacts.read_render(7, 1) == b"complete-page-png"


def test_failed_complete_page_persists_a_user_facing_failure(
    tmp_path: Path,
) -> None:
    app = _make_app()
    artifacts = TargetArtifacts(tmp_path / "project")

    class _BlockedTransport:
        async def generate(self, request):
            raise RuntimeError("finish_reason=SAFETY")

    with (
        patch("novel_to_comic.server.credited_job.get_db", return_value=object()),
        patch(
            "novel_to_comic.server.credited_job.reserve_credits",
            return_value=("reservation-1", "ledger-job-1"),
        ),
        patch("novel_to_comic.server.credited_job.assert_reservation_active"),
        patch("novel_to_comic.server.credited_job.release_reservation"),
        patch("novel_to_comic.server.credited_job.debit_model_usage"),
        patch("novel_to_comic.server.credited_job.ai_request_context"),
    ):
        job, _ = enqueue_complete_page_draw(
            app,
            project_name="project",
            user_id="user-1",
            project_id="project-1",
            project_dir=tmp_path / "project",
            config=Config(),
            compiled=_compile(tmp_path),
            adapter=VertexCompletePageAdapter(_BlockedTransport()),
            artifacts=artifacts,
            page=_page(),
        )
        with pytest.raises(RuntimeError, match="SAFETY"):
            asyncio.run(job.runner())

    failure = artifacts.read_page_failure(7)
    assert failure.classification == "provider_blocked"
    assert "declined" in failure.user_message
    assert failure.request_sha256 == _compile(tmp_path).request.request_sha256
    assert failure.phase == "generation"


def test_failed_ocr_is_recorded_as_analysis_failure_without_losing_render(
    tmp_path: Path,
) -> None:
    app = _make_app()
    artifacts = TargetArtifacts(tmp_path / "project")

    class _BrokenOCR:
        async def extract(self, image: bytes):
            raise ValueError("invalid OCR response shape")

    with (
        patch("novel_to_comic.server.credited_job.get_db", return_value=object()),
        patch(
            "novel_to_comic.server.credited_job.reserve_credits",
            return_value=("reservation-1", "ledger-job-1"),
        ),
        patch("novel_to_comic.server.credited_job.assert_reservation_active"),
        patch("novel_to_comic.server.credited_job.release_reservation"),
        patch("novel_to_comic.server.credited_job.debit_model_usage"),
        patch("novel_to_comic.server.credited_job.ai_request_context"),
    ):
        job, _ = enqueue_complete_page_draw(
            app,
            project_name="project",
            user_id="user-1",
            project_id="project-1",
            project_dir=tmp_path / "project",
            config=Config(),
            compiled=_compile(tmp_path),
            adapter=VertexCompletePageAdapter(
                _RecordingTransport(_provider_result())
            ),
            artifacts=artifacts,
            page=_page(),
            ocr=_BrokenOCR(),
        )
        with pytest.raises(ValueError, match="OCR"):
            asyncio.run(job.runner())

    assert artifacts.provenance_revisions(7) == (1,)
    failure = artifacts.read_page_failure(7)
    assert failure.phase == "analysis"
    assert failure.classification == "analysis_error"
    assert "already drawn" in failure.user_message


def test_render_analysis_is_reserved_for_and_debited_as_its_own_call(
    tmp_path: Path,
) -> None:
    # Generating a page and reading it back are two provider calls. Both are
    # billable, settled under one ledger job so credits round once.
    from novel_to_comic.config import PAGE_OCR_ESTIMATED_COST_USD
    from novel_to_comic.server.credits import credit_estimate_for_provider_cost
    app = _make_app()
    compiled = _compile(tmp_path)
    artifacts = TargetArtifacts(tmp_path / "project")
    analysis_usage = UsageRecord(
        provider="gemini",
        model="ocr-balanced",
        operation="text",
        input_tokens=1200,
        output_tokens=80,
        cost_usd=0.004,
        cost_source="provider",
    )

    class _OCR:
        async def extract(self, image: bytes):
            return ApiResult(
                value=OCRExtraction(
                    lettering=[
                        OCRTextObservation(id="ocr-1", text="It was the same face.")
                    ]
                ),
                usage=analysis_usage,
            )

    with (
        patch("novel_to_comic.server.credited_job.get_db", return_value=object()),
        patch(
            "novel_to_comic.server.credited_job.reserve_credits",
            return_value=("reservation-1", "ledger-job-1"),
        ) as reserve,
        patch("novel_to_comic.server.credited_job.assert_reservation_active"),
        patch("novel_to_comic.server.credited_job.release_reservation"),
        patch("novel_to_comic.server.credited_job.debit_model_usage") as debit,
        patch("novel_to_comic.server.credited_job.ai_request_context"),
    ):
        unanalysed, _ = enqueue_complete_page_draw(
            app,
            project_name="project",
            user_id="user-1",
            project_id="project-1",
            project_dir=tmp_path / "project",
            config=Config(),
            compiled=compiled,
            adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
            artifacts=TargetArtifacts(tmp_path / "unanalysed"),
            page=_page(),
        )
        without_analysis = reserve.call_args.args[-1]
        job, _ = enqueue_complete_page_draw(
            app,
            project_name="project-analysed",
            user_id="user-1",
            project_id="project-1",
            project_dir=tmp_path / "project",
            config=Config(),
            compiled=compiled,
            adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
            artifacts=artifacts,
            page=_page(),
            ocr=_OCR(),
        )
        with_analysis = reserve.call_args.args[-1]
        asyncio.run(job.runner())

    assert unanalysed is not job
    image_quote = credit_estimate_for_provider_cost(
        float(compiled.request.estimated_cost_usd), "draw", reserve=True,
    )
    checked_quote = credit_estimate_for_provider_cost(
        float(compiled.request.estimated_cost_usd) + float(PAGE_OCR_ESTIMATED_COST_USD),
        "draw", reserve=True,
    )
    assert without_analysis == image_quote["reserved_credits"]
    assert with_analysis == checked_quote["reserved_credits"]
    debited = [call.args[3] for call in debit.call_args_list]
    assert [usage.model for usage in debited] == [
        "gemini-3-pro-image",
        "ocr-balanced",
    ]
    # One ledger job, so whole credits are rounded once across both calls.
    assert {call.kwargs["job_id"] for call in debit.call_args_list} == {"ledger-job-1"}
    assert artifacts.read_analysis(7, 1).analysis_usage == analysis_usage


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
        patch("novel_to_comic.server.credited_job.assert_reservation_active"),
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
            operations=(("complete_page", "image-balanced"),),
        )
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(job.runner())

    debit.assert_not_called()
    release.assert_called_once()


def _ordered_page(*, state_first: bool) -> ComicPage:
    """One page showing Ward with a state and, elsewhere, without one."""

    stated = PageContent(
        id="content-state",
        order=1 if state_first else 2,
        beat_ids=["beat-1"],
        visual_intent="Ward, bloodied, holds the idol.",
        lettering=[
            LetteringItem(
                id="letter-1",
                kind="caption",
                text="It was the same face.",
                source_unit_ids=["source-1"],
            )
        ],
        entity_ids=["ward", "idol"],
        appearance_states={"ward": "ward-bloodied"},
    )
    plain = PageContent(
        id="content-plain",
        order=2 if state_first else 1,
        beat_ids=["beat-2"],
        visual_intent="Ward alone in the doorway.",
        entity_ids=["ward"],
    )
    content = [stated, plain] if state_first else [plain, stated]
    return ComicPage(
        revision=2,
        page_number=7,
        adaptation_revision=3,
        adaptation_sha256="a" * 64,
        emphasis="peak",
        density_intent="standard",
        layout_intent="Two moments.",
        content=content,
        reading_order=[*(item.id for item in content), "letter-1"],
    )


def test_reference_selection_does_not_depend_on_page_content_order(
    tmp_path: Path,
) -> None:
    # Selection is a property of the page. Deciding per content item silently
    # dropped an approved base reference depending on traversal order.
    files = _reference_files(tmp_path)
    selected = []
    for state_first in (True, False):
        compiled = compile_page_generation_request(
            _ordered_page(state_first=state_first),
            _edition(),
            _inventory(),
            files,
            retry=RetryProvenance(attempt=1),
        )
        selected.append(
            sorted(reference.id for reference in compiled.request.references)
        )

    assert selected[0] == selected[1]
    assert selected[0] == ["idol-ref", "ward-bloodied-ref", "ward-clean-ref"]


def test_correction_revisions_are_allocated_when_the_job_runs(tmp_path: Path) -> None:
    # Two corrections requested before either runs would otherwise both claim
    # the same revision, and the second would die on the immutable-artifact
    # guard after the route had already accepted it.
    import hashlib

    artifacts = TargetArtifacts(tmp_path / "project")
    page = _page()
    initial = asyncio.run(
        draw_complete_page(
            _compile(tmp_path),
            adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
            artifacts=artifacts,
            page=page,
        )
    )
    assert initial.render.revision == 1

    correction = PageRenderCorrection(
        issue_ids=("issue-hand",),
        page_number=7,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        parent_render_revision=1,
        parent_render_image_sha256=hashlib.sha256(b"complete-page-png").hexdigest(),
        mode="instructed",
        instruction="Correct the hand.",
    )
    corrected = asyncio.run(
        draw_complete_page(
            compile_page_generation_request(
                page,
                _edition(),
                _inventory(),
                _reference_files(tmp_path),
                retry=RetryProvenance(attempt=1),
                correction=correction,
                edit_source_bytes=b"complete-page-png",
            ),
            adapter=VertexCompletePageAdapter(
                _RecordingTransport(
                    _provider_result().model_copy(
                        update={"image_bytes": b"corrected-page-png"}
                    )
                )
            ),
            artifacts=artifacts,
            page=page,
            parent_render_revision=1,
        )
    )

    assert corrected.render.revision == 2
    assert corrected.render.parent_revision == 1
    assert artifacts.provenance_revisions(7) == (1, 2)
    assert artifacts.read_request(7, 2).correction == correction


def test_failed_page_correction_gets_new_retry_lineage(tmp_path: Path) -> None:
    artifacts = TargetArtifacts(tmp_path / "project")
    page = _page()
    correction = PageRenderCorrection(
        issue_ids=("issue-lettering",),
        page_number=page.page_number,
        comic_page_revision=page.revision,
        comic_page_sha256=page.content_sha256,
        parent_render_revision=1,
        parent_render_image_sha256=hashlib.sha256(b"parent-page").hexdigest(),
        mode="instructed",
        instruction="Correct the visible lettering.",
    )
    failed_request = compile_page_generation_request(
        page,
        _edition(),
        _inventory(),
        _reference_files(tmp_path),
        retry=RetryProvenance(attempt=1),
        correction=correction,
        edit_source_bytes=b"parent-page",
    ).request
    artifacts.write_request(failed_request, request_revision=2)

    retry = _aggregated_correction_retry(
        artifacts,
        page_number=page.page_number,
        issue_ids=correction.issue_ids,
    )

    assert retry == RetryProvenance(
        attempt=2,
        retries_request_sha256=failed_request.request_sha256,
    )


def test_draw_analyses_its_render_and_records_blocking_lettering_issues(
    tmp_path: Path,
) -> None:
    # Without this wiring no analysis artifact exists at all, and Finish blocks
    # every page for missing OCR status.
    artifacts = TargetArtifacts(tmp_path / "project")
    page = _page()

    class _OCR:
        async def extract(self, image: bytes):
            assert image
            return ApiResult(
                value=OCRExtraction(
                    lettering=[
                        OCRTextObservation(id="ocr-1", text="It was the WRONG face.")
                    ]
                ),
                usage=UsageRecord(
                    provider="gemini",
                    model="ocr-balanced",
                    operation="text",
                    input_tokens=1200,
                    output_tokens=80,
                    cost_usd=0.004,
                    cost_source="provider",
                ),
            )

    asyncio.run(
        draw_complete_page(
            _compile(tmp_path),
            adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
            artifacts=artifacts,
            page=page,
            ocr=_OCR(),
        )
    )

    analysis = artifacts.read_analysis(7, 1)
    assert [failure.code for failure in analysis.invariant_failures] == [
        "misspelled_lettering"
    ]
    issues = artifacts.read_issues(7)
    assert [issue.classification for issue in issues] == ["invariant_failure"]
    assert issues[0].correction_owner == "draw"


def test_a_stale_compiled_request_cannot_be_drawn(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="stale"):
        asyncio.run(
            draw_complete_page(
                _compile(tmp_path),
                adapter=VertexCompletePageAdapter(
                    _RecordingTransport(_provider_result())
                ),
                artifacts=TargetArtifacts(tmp_path / "project"),
                page=_page(revision=3),
            )
        )


def test_a_failed_read_back_leaves_the_paid_render_recorded(tmp_path: Path) -> None:
    # The image is already paid for when analysis runs. Losing its provenance
    # would let the page be generated — and charged — a second time.
    artifacts = TargetArtifacts(tmp_path / "project")

    class _OCR:
        async def extract(self, image: bytes):
            raise RuntimeError("gateway rejected the vision request")

    with pytest.raises(RuntimeError, match="gateway rejected"):
        asyncio.run(
            draw_complete_page(
                _compile(tmp_path),
                adapter=VertexCompletePageAdapter(
                    _RecordingTransport(_provider_result())
                ),
                artifacts=artifacts,
                page=_page(),
                ocr=_OCR(),
            )
        )

    assert artifacts.provenance_revisions(7) == (1,)
    assert artifacts.read_render(7, 1) == b"complete-page-png"
    assert not artifacts.analysis_path(7, 1).exists()


def test_an_existing_render_can_be_analyzed_without_redrawing_it(
    tmp_path: Path,
) -> None:
    artifacts = TargetArtifacts(tmp_path / "project")
    page = _page()

    class _OCR:
        def __init__(self, text: str) -> None:
            self.text = text

        async def extract(self, image: bytes):
            return ApiResult(
                value=OCRExtraction(
                    lettering=[OCRTextObservation(id="ocr-1", text=self.text)]
                ),
                usage=UsageRecord(
                    provider="gemini",
                    model="ocr-balanced",
                    operation="text",
                    input_tokens=1200,
                    output_tokens=80,
                ),
            )

    provenance = asyncio.run(
        draw_complete_page(
            _compile(tmp_path),
            adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
            artifacts=artifacts,
            page=page,
            defer_completion=True,
        )
    )
    assert not artifacts.analysis_path(7, 1).exists()

    analysis = asyncio.run(
        analyze_complete_page(
            page=page,
            render=provenance.render,
            image=artifacts.read_render(7, 1),
            ocr=_OCR("It was the same face."),
            artifacts=artifacts,
        )
    )

    assert analysis.lettering_valid is True
    assert analysis.analysis_usage is not None
    assert artifacts.read_analysis(7, 1) == analysis
    from novel_to_comic.page_drawing import reconcile_recovered_page_generation

    # Successful OCR alone cannot acknowledge an unsettled image operation.
    ledger = MagicMock()
    query = ledger.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value
    query.execute.return_value.data = []
    with patch("novel_to_comic.server.db.get_db", return_value=ledger):
        assert not reconcile_recovered_page_generation(artifacts=artifacts, render=provenance.render)
        assert artifacts.resumable_generation_request(7) is not None
        query.execute.return_value.data = [{"status": "settled"}]
        assert reconcile_recovered_page_generation(artifacts=artifacts, render=provenance.render)
    assert artifacts.resumable_generation_request(7) is None


def test_entity_scoped_state_names_do_not_collide(tmp_path: Path):
    from novel_to_comic.page_drawing import _selected_authorities
    page = _page().model_copy(update={"content": (PageContent(id="p1", order=1, beat_ids=("b1",), visual_intent="Alice waits.", entity_ids=("alice",), appearance_states={"alice": "wet"}),), "reading_order": ("p1",)})
    inventory = ApprovedVisualReferenceInventory(references=tuple(ApprovedVisualReference(id=f"{e}:wet", entity_id=e, appearance_state_id="wet", visual_anchor=f"{e}, wet coat") for e in ("alice", "bob")))
    assert [ref.id for ref in _selected_authorities(page, inventory)] == ["alice:wet"]


class _RecordingTransport:
    def __init__(self, result: CompletePageProviderResult) -> None:
        self.result = result
        self.submitted = []

    async def generate(self, request):
        self.submitted.append(request)
        return self.result


def test_visual_review_uses_exact_references_and_reuses_saved_result(tmp_path):
    from novel_to_comic.page_visual_review import review_page_visuals

    compiled = _compile(tmp_path)
    artifacts = TargetArtifacts(tmp_path)
    provenance = asyncio.run(draw_complete_page(
        compiled, adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
        artifacts=artifacts, page=_page(),
    ))
    generate = AsyncMock(return_value=ApiResult(value={
        'findings': [{'category': 'prop', 'panel_number': 1, 'observation': 'The idol has two horns.',
                      'expected': 'The reference has one horn.', 'correction': 'Restore the single horn.'}],
        'uncertain': ['The rear of the idol is occluded.'],
    }))
    kwargs = dict(config=Config(), page=_page(), render=provenance.render,
                  image=_provider_result().image_bytes, compiled=compiled, artifacts=artifacts, generate=generate)
    report = asyncio.run(review_page_visuals(**kwargs))
    repeated = asyncio.run(review_page_visuals(**kwargs))
    assert generate.await_count == 1
    assert repeated.value == report.value
    attachments = generate.call_args.kwargs['image_attachments']
    assert attachments[0][0] == _provider_result().image_bytes
    assert tuple(image for image, _ in attachments[1:]) == compiled.reference_bytes
    assert len(artifacts.read_issues(_page().page_number)) == 1
    assert artifacts.read_issues(_page().page_number)[0].classification == 'editorial_issue'
    assert artifacts.read_issues(_page().page_number)[0].status == 'open'


def test_final_page_prompt_preserves_geometry_reading_order_and_state_guard(tmp_path):
    from novel_to_comic.models.page import PinnedGeometry

    page = _page()
    content = page.content[0].model_copy(update={'pinned_geometry': PinnedGeometry(x=0, y=0, width=1, height=0.5)})
    page = page.model_copy(update={'content': (content,)})
    inventory = _inventory().model_copy(update={'references': tuple(
        ref.model_copy(update={'continuity_guard': 'Never restore the torn left sleeve.'})
        if ref.entity_id == 'ward' else ref for ref in _inventory().references
    )})
    request = compile_page_generation_request(page, _edition(), inventory, _reference_files(tmp_path), retry=RetryProvenance(attempt=1)).request
    brief = _provider_brief(request.prompt)
    assert brief["exact_lettering"]["reading_order"] == ["Panel 1", "Panel 1 lettering 1"]
    assert brief["canonical_comic_page"]["content"][0]["pinned_geometry"] == {
        "x": 0, "y": 0, "width": 1, "height": 0.5,
    }
    assert next(ref for ref in brief["approved_page_references"]
                if ref["visual_anchor"].startswith("Ward"))["continuity_guard"] == (
        "Never restore the torn left sleeve."
    )


def test_visual_review_route_compiles_current_authority_without_redrawing(tmp_path):
    from novel_to_comic.server.routers.pages import visual_review_page

    artifacts = TargetArtifacts(tmp_path)
    page = _page()
    files = _reference_files(tmp_path)
    artifacts.write_page(page)
    artifacts.write_book_edition(_edition())
    asyncio.run(draw_complete_page(_compile(tmp_path, files=files),
        adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
        artifacts=artifacts, page=page))

    async def admitted(**kwargs):
        return await kwargs['work']()

    with patch('novel_to_comic.server.routers.pages.approved_visual_inventory', return_value=_inventory()), \
         patch('novel_to_comic.server.routers.pages.approved_reference_files', return_value=files), \
         patch('novel_to_comic.server.credited_job.run_credited_page_check', side_effect=admitted), \
         patch('novel_to_comic.clients.text.generate_json', new_callable=AsyncMock,
               return_value=ApiResult(value={'findings': [], 'uncertain': []})) as generate:
        report = asyncio.run(visual_review_page(page.page_number, 'project',
            project=(tmp_path, Config(), None), user_id='user'))
        assert report.render_revision == 1
        assert report.findings == ()
        asyncio.run(visual_review_page(page.page_number, 'project',
            project=(tmp_path, Config(), None), user_id='user'))
        assert generate.await_count == 1
    assert artifacts.provenance_revisions(page.page_number) == (1,)


def test_draw_estimate_is_read_only_and_includes_lettering_check(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from novel_to_comic.config import PAGE_OCR_ESTIMATED_COST_USD
    from novel_to_comic.server.credits import credit_estimate_for_provider_cost
    from novel_to_comic.server.deps import get_project
    from novel_to_comic.server.routers.pages import router

    artifacts = TargetArtifacts(tmp_path)
    page = _page()
    edition = _edition(production_page_capability_profile())
    files = _reference_files(tmp_path)
    artifacts.write_page(page)
    artifacts.write_book_edition(edition)
    compiled = compile_page_generation_request(
        page, edition, _inventory(), files, retry=RetryProvenance(attempt=1),
    )
    before = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)
    with patch("novel_to_comic.server.routers.pages.approved_visual_inventory", return_value=_inventory()), \
         patch("novel_to_comic.server.routers.pages.approved_reference_files", return_value=files), \
         patch("novel_to_comic.server.credited_job.reserve_credits") as reserve:
        client = TestClient(app)
        response = client.get("/pages/7/generate/estimate?depiction=less_graphic")
        assert response.status_code == 200
        assert response.json() == dict(credit_estimate_for_provider_cost(
            float(compiled.request.estimated_cost_usd) + float(PAGE_OCR_ESTIMATED_COST_USD),
            "draw", reserve=True,
        ))
        assert response.json()["reserved_credits"] >= response.json()["estimate_credits"] > 0
        assert client.get("/pages/7/generate/estimate?depiction=unknown").status_code == 422
        assert client.get("/pages/7/analyze/estimate").status_code == 409
        reserve.assert_not_called()
    after = {path.relative_to(tmp_path): path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}
    assert after == before


def test_existing_page_checks_quote_holds_without_redrawing(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from novel_to_comic.server.deps import get_project
    from novel_to_comic.server.routers.pages import router

    artifacts = TargetArtifacts(tmp_path)
    page = _page()
    files = _reference_files(tmp_path)
    artifacts.write_page(page)
    artifacts.write_book_edition(_edition())
    asyncio.run(draw_complete_page(
        _compile(tmp_path, files=files),
        adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
        artifacts=artifacts, page=page,
    ))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)
    with patch("novel_to_comic.server.credited_job.reserve_credits") as reserve, \
         patch("novel_to_comic.server.routers.pages.approved_visual_inventory", return_value=_inventory()), \
         patch("novel_to_comic.server.routers.pages.approved_reference_files", return_value=files):
        client = TestClient(app)
        for check in ("analyze", "visual-review"):
            response = client.get(f"/pages/7/{check}/estimate")
            assert response.status_code == 200
            assert response.json()["reserved_credits"] >= response.json()["estimate_credits"] > 0
        assert client.get("/pages/7/generate/estimate").status_code == 409
        reserve.assert_not_called()
    assert artifacts.provenance_revisions(7) == (1,)


def test_batch_quote_skips_paid_pages_and_sums_individual_holds(tmp_path: Path) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from types import SimpleNamespace
    from novel_to_comic.server.deps import get_project
    from novel_to_comic.server.routers.pages import router

    artifacts = TargetArtifacts(tmp_path)
    first = _page()
    remaining = [
        ComicPage.model_validate({
            **first.model_dump(exclude={"content_sha256"}),
            "page_number": number,
        })
        for number in (8, 9)
    ]
    files = _reference_files(tmp_path)
    for page in [first, *remaining]:
        artifacts.write_page(page)
    asyncio.run(draw_complete_page(
        _compile(tmp_path, files=files),
        adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
        artifacts=artifacts, page=first,
    ))
    artifacts.write_book_edition(_edition(production_page_capability_profile()))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_project] = lambda: (tmp_path, Config(), None)
    with patch.object(TargetArtifacts, "read_plan", return_value=SimpleNamespace(pages=[first, *remaining])), \
         patch("novel_to_comic.server.routers.pages.approved_visual_inventory", return_value=_inventory()), \
         patch("novel_to_comic.server.routers.pages.approved_reference_files", return_value=files):
        client = TestClient(app)
        batch = client.get("/pages/generate/estimate")
        single = client.get("/pages/8/generate/estimate")
        assert batch.status_code == single.status_code == 200
        assert batch.json()["estimate_credits"] == single.json()["estimate_credits"] * 2
        assert batch.json()["reserved_credits"] == single.json()["reserved_credits"] * 2
    assert artifacts.provenance_revisions(7) == (1,)
    assert artifacts.provenance_revisions(8) == ()
    assert artifacts.provenance_revisions(9) == ()


@pytest.mark.parametrize("publication_step", ["write_render", "write_provenance"])
def test_interrupted_paid_result_publication_recovers_without_resubmission(
    tmp_path, monkeypatch, publication_step,
):
    artifacts = TargetArtifacts(tmp_path / "project")
    transport = _RecordingTransport(_provider_result())
    adapter = VertexCompletePageAdapter(transport)
    compiled = _compile(tmp_path)
    original = getattr(artifacts, publication_step)
    def crash(*args, **kwargs):
        raise OSError("publication interrupted")
    monkeypatch.setattr(artifacts, publication_step, crash)
    with pytest.raises(OSError, match="publication interrupted"):
        asyncio.run(draw_complete_page(compiled, adapter=adapter, artifacts=artifacts, page=_page()))
    monkeypatch.setattr(artifacts, publication_step, original)
    from novel_to_comic.server.routers.pages import _generation_retry

    # Exercise the route's retry decision, not an artificial replay of the
    # original in-memory compiled object after publication has failed.
    compiled = compile_page_generation_request(
        _page(), _edition(), _inventory(), _reference_files(tmp_path),
        retry=_generation_retry(artifacts, 7),
    )

    class UnavailableOCR:
        async def extract(self, image):
            raise RuntimeError("read-back unavailable after publication")

    with pytest.raises(RuntimeError, match="read-back unavailable"):
        asyncio.run(draw_complete_page(
            compiled, adapter=adapter, artifacts=artifacts, page=_page(),
            ocr=UnavailableOCR(),
        ))
    # Recovery has now published provenance and removed the pending journal.
    # A second route retry must still use the same paid request identity.
    compiled = compile_page_generation_request(
        _page(), _edition(), _inventory(), _reference_files(tmp_path),
        retry=_generation_retry(artifacts, 7),
    )
    recovered = asyncio.run(
        draw_complete_page(compiled, adapter=adapter, artifacts=artifacts, page=_page())
    )
    assert len(transport.submitted) == 1
    assert artifacts.read_render(7, 1) == transport.result.image_bytes
    assert artifacts.read_provenance(7, 1) == recovered
    assert recovered.usage == transport.result.usage


def test_legacy_orphan_image_blocks_before_paid_submission(tmp_path):
    artifacts = TargetArtifacts(tmp_path / "project")
    artifacts.write_render(page_number=7, render_revision=1, image=b"valuable existing artwork")
    transport = _RecordingTransport(_provider_result())
    with pytest.raises(ValueError, match="Interrupted page persistence"):
        asyncio.run(draw_complete_page(
            _compile(tmp_path), adapter=VertexCompletePageAdapter(transport),
            artifacts=artifacts, page=_page(),
        ))
    assert transport.submitted == []
    assert artifacts.read_render(7, 1) == b"valuable existing artwork"


def test_explicit_occupied_revision_is_rejected_before_paid_submission(tmp_path):
    artifacts = TargetArtifacts(tmp_path / "project")
    transport = _RecordingTransport(_provider_result())
    adapter = VertexCompletePageAdapter(transport)
    compiled = _compile(tmp_path)
    asyncio.run(draw_complete_page(compiled, adapter=adapter, artifacts=artifacts, page=_page()))
    compiled = compile_page_generation_request(
        _page(), _edition(), _inventory(), _reference_files(tmp_path),
        retry=RetryProvenance(
            attempt=2, retries_request_sha256=compiled.request.request_sha256,
        ),
    )
    with pytest.raises(ValueError, match="occupied"):
        asyncio.run(draw_complete_page(
            compiled, adapter=adapter, artifacts=artifacts, page=_page(), render_revision=1,
        ))
    assert len(transport.submitted) == 1


def test_region_only_correction_changes_native_content_without_shifting_references(tmp_path):
    from novel_to_comic.models.draw import ObservedRegion
    from litellm_handlers.vertex_multimodal import _exact_complete_page_contents

    page = _page()
    parent_bytes = b"parent-page"
    base = dict(
        issue_ids=("issue-hand",), page_number=page.page_number,
        comic_page_revision=page.revision, comic_page_sha256=page.content_sha256,
        parent_render_revision=1,
        parent_render_image_sha256=hashlib.sha256(parent_bytes).hexdigest(),
        mode="region_targeted", instruction="Restore the hand.",
    )
    provider_contents = []
    images = [object(), object(), object()]
    for name, polygon in (
        ("left", ((0.0, 0.0), (0.4, 0.0), (0.4, 0.5))),
        ("right", ((0.6, 0.0), (1.0, 0.0), (1.0, 0.5))),
    ):
        correction = PageRenderCorrection.model_validate({
            **base,
            "detected_region_ids": (name,),
            "resolved_regions": (ObservedRegion(id=name, polygon=polygon),),
        })
        request = compile_page_generation_request(
            page, _edition(), _inventory(), _reference_files(tmp_path),
            retry=RetryProvenance(attempt=1), correction=correction,
            edit_source_bytes=parent_bytes,
        ).request
        brief = _provider_brief(request.prompt)
        region = brief["complete_page_correction"]["parent_coordinate_regions"][0]
        assert region["polygon"] == [{"x": x, "y": y} for x, y in polygon]
        contents = _exact_complete_page_contents(request.model_dump(mode="json"), images)
        for index, reference in enumerate(brief["approved_page_references"]):
            assert reference["image"] in contents[3 + index * 2]
        assert request.lettering == page.content[0].lettering
        provider_contents.append(contents)
    assert provider_contents[0][:-1] == provider_contents[1][:-1]
    assert provider_contents[0][-1] != provider_contents[1][-1]


def test_visual_review_preserves_producing_depiction_and_rejects_wrong_lineage(tmp_path):
    from novel_to_comic.page_visual_review import visual_review_input_digest, visual_review_prompt

    page = _page()
    current = _compile(tmp_path)
    producing = compile_page_generation_request(
        page, _edition(), _inventory(), _reference_files(tmp_path),
        retry=RetryProvenance(attempt=1), depiction="less_graphic",
    )
    artifacts = TargetArtifacts(tmp_path / "project")
    rendered = asyncio.run(draw_complete_page(
        producing, adapter=VertexCompletePageAdapter(_RecordingTransport(_provider_result())),
        artifacts=artifacts, page=page,
    ))
    prompt = visual_review_prompt(compiled=current, producing_request=producing.request)
    data = _provider_brief(prompt)
    assert data["producing_specification"] == producing.request.prompt
    assert data["generation_specification"] == current.request.prompt
    args = dict(
        config=Config(), page=page, render=rendered.render,
        image=_provider_result().image_bytes, compiled=current,
    )
    assert visual_review_input_digest(**args, producing_request=producing.request) != (
        visual_review_input_digest(**args)
    )
    with pytest.raises(ValueError, match="producing instructions"):
        visual_review_input_digest(**args, producing_request=current.request)


def test_less_graphic_intent_survives_correction_and_visual_review(tmp_path):
    from tests.test_page_corrections import _adaptation, _page as correction_page, _source
    from novel_to_comic.page_drawing import correct_complete_page, prepare_page_correction
    from novel_to_comic.page_visual_review import visual_review_prompt

    artifacts = TargetArtifacts(tmp_path / "project")
    source = _source()
    artifacts.write_source(source)
    artifacts.write_adaptation(_adaptation(source))
    page = correction_page()
    artifacts.write_page(page)
    edition = _edition()
    artifacts.write_book_edition(edition)
    inventory = ApprovedVisualReferenceInventory(references=())
    producing = compile_page_generation_request(
        page, edition, inventory, {}, retry=RetryProvenance(attempt=1),
        depiction="less_graphic",
    )
    adapter = VertexCompletePageAdapter(_RecordingTransport(_provider_result()))
    original = asyncio.run(draw_complete_page(
        producing, adapter=adapter, artifacts=artifacts, page=page,
    ))
    prepared = prepare_page_correction(
        page=page, edition=edition, inventory=inventory, reference_files={},
        retry=RetryProvenance(attempt=1), parent=original.render, changes=(),
        note="Keep the door edge readable.", artifacts=artifacts,
    )
    assert producing.request.prompt in prepared.correction.retained_instructions
    assert prepared.compiled.edit_source_bytes == artifacts.read_render(page.page_number, 1)
    assert not artifacts.issues_path(page.page_number).exists()
    corrected = asyncio.run(correct_complete_page(
        prepared.compiled, issue=None, adapter=adapter, artifacts=artifacts, page=page,
    ))
    assert artifacts.resumable_generation_request(page.page_number) is None
    assert not artifacts.issues_path(page.page_number).exists()
    following = prepare_page_correction(
        page=page, edition=edition, inventory=inventory, reference_files={},
        retry=RetryProvenance(attempt=1), parent=corrected.render, changes=(),
        note="Make the foreground hand readable.", artifacts=artifacts,
    )
    assert producing.request.prompt in following.correction.retained_instructions
    assert "Keep the door edge readable." in following.correction.retained_instructions
    current = compile_page_generation_request(
        page, edition, inventory, {}, retry=RetryProvenance(attempt=1),
    )
    brief = _provider_brief(visual_review_prompt(
        compiled=current, producing_request=prepared.compiled.request,
    ))
    assert brief["producing_specification"] == prepared.compiled.request.prompt
    assert brief["generation_specification"] == current.request.prompt
    assert corrected.render.parent_revision == original.render.revision
    assert following.compiled.reference_bytes == ()

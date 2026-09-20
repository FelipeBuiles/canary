"""Provider-free tests of identity planning, resume and pixel-bound review."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from novel_to_comic import artifacts
from novel_to_comic import cast_design as design
from novel_to_comic.stages import s3_cast
from novel_to_comic.target_artifacts import ArtifactInvalid, TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord
from .test_cast_style_authority import _project, _save_design


def _cast(tmp_path):
    config, bible, proof = _project(tmp_path, "image-gemini-pro")
    bible.characters.append(bible.characters[0].model_copy(update={"id": "doctor", "name": "Doctor"}))
    artifacts.write_story_bible(tmp_path, bible)
    plan = _save_design(config, tmp_path, bible)
    for c in bible.characters:
        path = artifacts.character_ref_sheet_path(tmp_path, c.id)
        path.parent.mkdir(parents=True)
        Image.new("RGB", (64, 64), "orange").save(path)
    return config, bible, plan


def test_design_is_reused_and_source_facts_remain_verbatim(tmp_path):
    config, bible, plan = _cast(tmp_path)
    original = (tmp_path / "story_bible.json").read_bytes()
    with patch.object(design.text, "generate_json", new_callable=AsyncMock) as generate:
        assert asyncio.run(design.ensure_design(config, tmp_path, bible, MagicMock())) == plan
    generate.assert_not_awaited()
    for c in bible.characters:
        request = s3_cast._character_generation_input(config, bible, c, design=plan)
        assert request.prompt.subjects[0].identity == c.visual_anchor
        assert c.id + " facial landmarks" in request.prompt.constraints
    assert (tmp_path / "story_bible.json").read_bytes() == original


@pytest.mark.parametrize("change", ["style", "source"])
def test_design_staleness_is_explicit(tmp_path, change):
    config, bible, _ = _cast(tmp_path)
    if change == "style":
        config.style_template += " new style"
    else:
        bible.characters[0].visual_anchor += ", red hair"
    with pytest.raises(ValueError, match="stale"):
        design.read_design(config, tmp_path, bible)


@pytest.mark.parametrize("fault", ["missing", "duplicate", "same_face"])
def test_design_rejects_incomplete_or_collapsed_roster(tmp_path, fault):
    _, bible, plan = _cast(tmp_path)
    if fault == "missing":
        plan.characters.pop()
    elif fault == "duplicate":
        plan.characters.append(plan.characters[0])
    else:
        plan.characters[1] = plan.characters[0].model_copy(update={"character_id": "doctor"})
    with pytest.raises(ValueError):
        design.validate_designs(plan, bible)


def test_invalid_design_response_records_usage_and_never_generates_images(tmp_path):
    config, bible, _ = _cast(tmp_path)
    TargetArtifacts(tmp_path).cast_design_path.unlink()
    ctx = MagicMock()
    usage = UsageRecord(provider="test", model="test", operation="text", input_tokens=10, output_tokens=10)

    async def response(**kwargs):
        kwargs["response_sink"](ApiResult(value='{"characters": []}', usage=usage))
        return ApiResult(value={"characters": []}, usage=usage)

    with patch.object(design.text, "generate_json", side_effect=response), \
         patch.object(s3_cast, "submit_non_panel_request", new_callable=AsyncMock) as images:
        with pytest.raises(ValueError, match="every character"):
            asyncio.run(design.ensure_design(config, tmp_path, bible, ctx))
    ctx.record_api_usage.assert_called_once_with(usage)
    images.assert_not_awaited()
    assert not TargetArtifacts(tmp_path).cast_design_path.exists()


def test_visual_review_uses_images_is_cached_and_expires_on_replacement(tmp_path):
    config, bible, _ = _cast(tmp_path)
    result = {"issues": [{"character_ids": ["sailor", "doctor"], "concern": "lookalike",
                          "evidence": "Same narrow jaw and hairline", "suggestion": "Broaden the doctor's jaw"}]}
    with patch.object(design.text, "generate_json", new_callable=AsyncMock,
                      return_value=ApiResult(value=result)) as generate:
        asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))
        asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))
    assert generate.await_count == 1
    assert len(generate.call_args.kwargs["image_attachments"]) == 1
    assert generate.call_args.kwargs["retry_transport"] is False
    assert design.review_status(config, tmp_path) == {"status": "current", **result}
    Image.new("RGB", (64, 64), "blue").save(artifacts.character_ref_sheet_path(tmp_path, "doctor"))
    assert design.review_status(config, tmp_path) == {"status": "stale", "issues": []}


def test_review_rejects_unknown_ids_and_changed_pixels(tmp_path):
    config, bible, _ = _cast(tmp_path)
    invalid = {"issues": [{"character_ids": ["unknown"], "concern": "identity", "evidence": "x", "suggestion": "y"}]}
    with patch.object(design.text, "generate_json", new_callable=AsyncMock, return_value=ApiResult(value=invalid)):
        with pytest.raises(ValueError, match="invalid character"):
            asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))

    async def replaced(**kwargs):
        Image.new("RGB", (64, 64), "blue").save(artifacts.character_ref_sheet_path(tmp_path, "doctor"))
        return ApiResult(value={"issues": []})

    with patch.object(design.text, "generate_json", side_effect=replaced):
        with pytest.raises(ValueError, match="changed during review"):
            asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))
    assert not TargetArtifacts(tmp_path).cast_review_path.exists()


def test_contact_sheets_include_large_cast_without_dropping_characters(tmp_path):
    config, bible, _ = _cast(tmp_path)
    for i in range(27):
        c = bible.characters[0].model_copy(update={"id": f"person_{i}"})
        bible.characters.append(c)
        path = artifacts.character_ref_sheet_path(tmp_path, c.id)
        path.parent.mkdir()
        Image.new("RGB", (64, 64), "blue").save(path)
    assert len(design._contact_sheets(tmp_path, bible)) == 3


def test_incompatible_artifact_requires_rerun(tmp_path):
    config, bible, _ = _cast(tmp_path)
    TargetArtifacts(tmp_path).cast_design_path.write_text(json.dumps({"schema_version": 0}))
    with pytest.raises(ArtifactInvalid, match="Rerun Cast"):
        design.read_design(config, tmp_path, bible)


def test_style_board_failure_never_falls_back_to_people(tmp_path):
    config, _, _ = _project(tmp_path, "image-gemini-pro")
    with patch.object(s3_cast, "submit_non_panel_request", new_callable=AsyncMock, side_effect=RuntimeError("failed")):
        with pytest.raises(RuntimeError, match="failed"):
            asyncio.run(s3_cast._generate_character_style_board(config, tmp_path, MagicMock()))


def test_missing_design_rejected_before_correction_rewrite(tmp_path):
    from fastapi import HTTPException
    from novel_to_comic.cast_instructions import apply_asset_instruction
    config, _, _ = _project(tmp_path, "image-gemini-pro")
    with patch.object(design.text, "generate_json", new_callable=AsyncMock) as generate:
        with pytest.raises(HTTPException) as error:
            asyncio.run(apply_asset_instruction(config, tmp_path, MagicMock(), "u", "p", "character", "sailor", "Different face"))
    assert error.value.status_code == 409
    generate.assert_not_awaited()


@pytest.mark.parametrize("failed_group", ["_generate_character_state_refs", "_generate_location_plates", "_generate_prop_refs"])
def test_cast_item_failure_cannot_complete_checkpoint(tmp_path, failed_group):
    from contextlib import ExitStack
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.state import create_initial_state, load_state, StageStatus

    config, bible, _ = _cast(tmp_path)
    state = create_initial_state("test", "novel.txt")
    events = []
    ctx = StageRuntime("cast", state, tmp_path, on_event=events.append)

    async def fail_item(*args):
        ctx.record_item_failed("sailor:alternate")
    with ExitStack() as stack:
        for helper in ("ensure_design", "_generate_character_style_board", "_generate_character_refs",
                       "_generate_character_state_refs", "review_cast", "_generate_location_plates", "_generate_prop_refs"):
            stack.enter_context(patch.object(s3_cast, helper, new_callable=AsyncMock,
                side_effect=fail_item if helper == failed_group else None))
        with pytest.raises(ValueError, match="Resume Cast"):
            asyncio.run(s3_cast.run(config, tmp_path, ctx))
    saved = load_state(tmp_path).stages["cast"]
    assert saved.status == StageStatus.FAILED
    assert "sailor:alternate" in saved.items_failed
    assert not any(event["type"] == "stage_complete" for event in events)
    assert any(event["type"] == "stage_fail" for event in events)


def test_cast_approval_requires_appearances_even_with_current_identity_review(tmp_path):
    from novel_to_comic.models.story_bible import AppearanceState
    from novel_to_comic.state import StageState, StageStatus
    config, bible, _ = _cast(tmp_path)
    bible.characters[0].appearance_states = [AppearanceState(
        id="altered", label="Altered appearance", visual_anchor="changed clothing", visually_significant=True)]
    artifacts.write_story_bible(tmp_path, bible)
    stage = StageState(status=StageStatus.AWAITING_REVIEW, items_done=6, items_total=6)
    with patch.object(s3_cast, "review_status", return_value={"status": "current"}):
        assert "missing work" in s3_cast.cast_approval_blocker(config, tmp_path, stage)
        appearance = artifacts.character_state_ref_sheet_path(tmp_path, "sailor", "altered")
        appearance.parent.mkdir(parents=True)
        Image.new("RGB", (32, 32), "orange").save(appearance)
        assert s3_cast.cast_approval_blocker(config, tmp_path, stage) is None
        stage.items_failed = ["sailor:altered"]
        assert "missing work" in s3_cast.cast_approval_blocker(config, tmp_path, stage)


def test_cast_approval_requires_current_visual_review(tmp_path):
    from novel_to_comic.state import StageState, StageStatus
    config, _, _ = _cast(tmp_path)
    stage = StageState(status=StageStatus.AWAITING_REVIEW, items_done=5, items_total=5)
    assert "visual review" in s3_cast.cast_approval_blocker(config, tmp_path, stage)


def test_status_and_approval_share_cast_blocker_without_changing_old_checkpoint(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fastapi import HTTPException
    from novel_to_comic.server.routers import projects, pipeline
    from novel_to_comic.state import create_initial_state, StageStatus
    config, _, _ = _cast(tmp_path)
    state = create_initial_state("test", "novel.txt")
    state.stages["cast"].status = StageStatus.AWAITING_REVIEW
    state.stages["cast"].items_failed = ["sailor:alternate", "cast_visual_review"]
    app = SimpleNamespace(state=SimpleNamespace(generation_jobs={}, running_tasks={}, style_tasks={}))
    request = SimpleNamespace(app=app)
    db = MagicMock()
    db.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value.data = []
    monkeypatch.setattr(projects, "get_db", lambda: db)
    status = projects.project_status(request, "test", (tmp_path, config, state), "account")
    blocker = status["stages"]["cast"]["approval_blocker"]
    assert "missing work" in blocker
    with pytest.raises(HTTPException) as error:
        asyncio.run(pipeline.approve("cast", "test", request, (tmp_path, config, state), "account"))
    assert error.value.status_code == 409
    assert error.value.detail == {"code": "cast_approval_rejected", "message": blocker}
    assert state.stages["cast"].status == StageStatus.AWAITING_REVIEW


def test_missing_cast_source_is_a_blocker_not_a_status_read_failure(tmp_path):
    from novel_to_comic.config import Config
    from novel_to_comic.state import StageState
    assert "source artifacts" in s3_cast.cast_approval_blocker(Config(), tmp_path, StageState())

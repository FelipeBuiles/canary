"""Provider-free tests of identity planning, resume and pixel-bound review."""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from novel_to_comic import look_assets
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
    with pytest.raises(ValueError, match="missing for Gustaf"):
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
    usages = []

    async def response(**kwargs):
        usage = UsageRecord(provider="test", model="test", operation="text", input_tokens=10, output_tokens=10)
        usages.append(usage)
        kwargs["response_sink"](ApiResult(value='{"characters": []}', usage=usage))
        return ApiResult(value={"characters": []}, usage=usage)

    with patch.object(design.text, "generate_json", side_effect=response), \
         patch.object(look_assets, "submit_non_panel_request", new_callable=AsyncMock) as images:
        with pytest.raises(ValueError, match="every character"):
            asyncio.run(design.ensure_design(config, tmp_path, bible, ctx))
    assert ctx.record_api_usage.call_count == 2
    assert [call.args[0] for call in ctx.record_api_usage.call_args_list] == usages
    images.assert_not_awaited()
    assert not TargetArtifacts(tmp_path).cast_design_path.exists()


@pytest.mark.parametrize("fault", ["missing", "repeated", "unexpected", "same_face", "shape"])
def test_completed_invalid_design_is_corrected_once_before_saving_or_image_work(tmp_path, fault):
    config, bible, plan = _cast(tmp_path)
    # These are the two IDs required by the production Everest run. The source
    # facts remain synthetic; reproduction makes no provider calls.
    for character, choice, cid in zip(bible.characters, plan.characters, ("char_narrator", "char_jimmy")):
        character.id = choice.character_id = cid
    TargetArtifacts(tmp_path).cast_design_path.unlink()
    valid = {"characters": [choice.model_dump() for choice in plan.characters]}
    invalid = json.loads(json.dumps(valid))
    if fault == "missing":
        invalid["characters"].pop()
    elif fault == "repeated":
        invalid["characters"][1]["character_id"] = "char_narrator"
    elif fault == "unexpected":
        invalid["characters"][0]["character_id"] = "Narrator (Boss)"
    elif fault == "same_face":
        invalid["characters"][1] = {**invalid["characters"][0], "character_id": "char_jimmy"}
    else:
        invalid = {"designs": invalid["characters"]}
    ctx = MagicMock()
    calls = []
    usages = [UsageRecord(call_id=f"design_{i}", provider="test", model="test", operation="text",
                          input_tokens=10, output_tokens=10) for i in range(2)]

    async def respond(**kwargs):
        assert not TargetArtifacts(tmp_path).cast_design_path.exists()
        assert kwargs["retry_transport"] is False and kwargs["retry_invalid_json"] is False
        schema = kwargs["json_schema"]
        assert schema["properties"]["characters"]["minItems"] == 2
        assert schema["properties"]["characters"]["maxItems"] == 2
        assert schema["$defs"]["CharacterDesign"]["properties"]["character_id"]["enum"] == [
            "char_jimmy", "char_narrator"]
        index = len(calls)
        calls.append(kwargs)
        value = invalid if index == 0 else valid
        kwargs["response_sink"](ApiResult(value=json.dumps(value), usage=usages[index]))
        return ApiResult(value=value, usage=usages[index])

    with patch.object(design.text, "generate_json", side_effect=respond), \
         patch.object(look_assets, "submit_non_panel_request", new_callable=AsyncMock) as images:
        accepted = asyncio.run(design.ensure_design(config, tmp_path, bible, ctx))

    assert len(calls) == 2
    assert calls[1]["user_content"].startswith(calls[0]["user_content"])
    assert "previous design response failed validation" in calls[1]["user_content"]
    assert "char_narrator" in calls[1]["user_content"] and "char_jimmy" in calls[1]["user_content"]
    assert accepted.characters == plan.characters
    assert TargetArtifacts(tmp_path).read_cast_design() == accepted
    assert [call.args[0] for call in ctx.record_api_usage.call_args_list] == usages
    ctx.record_item_done.assert_called_once_with(cost=0.0)
    images.assert_not_awaited()


@pytest.mark.parametrize("after_rejection", [False, True])
def test_design_transport_failure_never_retries_or_loses_completed_usage(tmp_path, after_rejection):
    config, bible, _ = _cast(tmp_path)
    TargetArtifacts(tmp_path).cast_design_path.unlink()
    ctx = MagicMock()
    usage = UsageRecord(call_id="completed_design", provider="test", model="test", operation="text")
    calls = []

    async def respond(**kwargs):
        calls.append(kwargs)
        if after_rejection and len(calls) == 1:
            kwargs["response_sink"](ApiResult(value='{"characters": []}', usage=usage))
            return ApiResult(value={"characters": []}, usage=usage)
        raise TimeoutError("submission outcome unknown")

    with patch.object(design.text, "generate_json", side_effect=respond):
        with pytest.raises(TimeoutError, match="outcome unknown"):
            asyncio.run(design.ensure_design(config, tmp_path, bible, ctx))
    assert len(calls) == (2 if after_rejection else 1)
    if after_rejection:
        ctx.record_api_usage.assert_called_once_with(usage)
    else:
        ctx.record_api_usage.assert_not_called()
    assert not TargetArtifacts(tmp_path).cast_design_path.exists()


def test_design_estimate_includes_the_bounded_correction_only_for_missing_designs(tmp_path):
    config, bible, _ = _cast(tmp_path)
    with patch.object(design, "estimate_text_cost", return_value=1.0), \
         patch.object(design, "estimate_review_cost", return_value=10.0):
        assert design.estimate_design_review(config, tmp_path, bible) == 10.0
        TargetArtifacts(tmp_path).cast_design_path.unlink()
        assert design.estimate_design_review(config, tmp_path, bible) == 13.0


@pytest.mark.parametrize("after_rejection", [False, True])
def test_unparseable_design_stops_and_stage_records_each_completed_attempt_once(tmp_path, after_rejection):
    from novel_to_comic.ai.errors import AIStructuredResponseError
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.state import create_initial_state, StageStatus

    config, bible, _ = _cast(tmp_path)
    TargetArtifacts(tmp_path).cast_design_path.unlink()
    state = create_initial_state("test", "novel.txt")
    ctx = StageRuntime("cast", state, tmp_path, on_event=lambda _event: None)
    usages = []

    async def respond(**kwargs):
        usage = UsageRecord(provider="test", model="test", operation="text", cost_usd=0.1)
        usages.append(usage)
        rejected = after_rejection and len(usages) == 1
        kwargs["response_sink"](ApiResult(value='{"characters": []}' if rejected else '{', usage=usage))
        if rejected:
            return ApiResult(value={"characters": []}, usage=usage)
        raise AIStructuredResponseError("invalid JSON", usage_records=[usage])

    with patch.object(design.text, "generate_json", side_effect=respond):
        with pytest.raises(AIStructuredResponseError, match="invalid JSON"):
            with ctx.execute():
                asyncio.run(design.ensure_design(config, tmp_path, bible, ctx))

    assert len(usages) == (2 if after_rejection else 1)
    stage = state.stages["cast"]
    assert stage.status == StageStatus.FAILED
    assert [entry["call_id"] for entry in stage.usage_log] == [u.call_id for u in usages]
    assert stage.cost_usd == pytest.approx(len(usages) * 0.1)
    assert not TargetArtifacts(tmp_path).cast_design_path.exists()


def test_design_requires_characters_in_provider_schema_and_rejects_missing_key(tmp_path):
    config, bible, _ = _cast(tmp_path)
    TargetArtifacts(tmp_path).cast_design_path.unlink()
    ctx = MagicMock()

    async def response(**kwargs):
        schema = kwargs["json_schema"]
        assert "characters" in schema["required"]
        return ApiResult(value={"designs": []})

    with patch.object(design.text, "generate_json", side_effect=response), \
         patch.object(look_assets, "submit_non_panel_request", new_callable=AsyncMock) as images:
        with pytest.raises(ValueError, match="invalid character roster"):
            asyncio.run(design.ensure_design(config, tmp_path, bible, ctx))

    images.assert_not_awaited()
    assert not TargetArtifacts(tmp_path).cast_design_path.exists()


def test_visual_review_uses_images_is_cached_and_expires_on_replacement(tmp_path):
    config, bible, _ = _cast(tmp_path)
    result = {"issues": [{"character_ids": ["sailor", "doctor"], "location_ids": [], "concern": "lookalike",
                          "evidence": "Same narrow jaw and hairline", "suggestion": "Broaden the doctor's jaw"}]}
    with patch.object(design.text, "generate_json", new_callable=AsyncMock,
                      return_value=ApiResult(value=result)) as generate:
        asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))
        asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))
    assert generate.await_count == 1
    # The selected proof leads as rendering authority, then the character contact sheet.
    assert len(generate.call_args.kwargs["image_attachments"]) == 2
    assert "Image 1 is the selected style proof" in generate.call_args.kwargs["system_prompt"]
    assert generate.call_args.kwargs["retry_transport"] is False
    assert design.review_status(config, tmp_path) == {
        "status": "current", **result, "dismissed": 0, "reviewing": False}
    Image.new("RGB", (64, 64), "blue").save(artifacts.character_ref_sheet_path(tmp_path, "doctor"))
    assert design.review_status(config, tmp_path) == {
        "status": "stale", "issues": [], "dismissed": 0, "reviewing": False, "characters": 2}


def _review_with(config, tmp_path, bible, issues):
    with patch.object(design.text, "generate_json", new_callable=AsyncMock,
                      return_value=ApiResult(value={"issues": issues})):
        asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))


def test_dismissed_note_stays_hidden_for_the_same_sheet_and_returns_when_it_changes(tmp_path):
    config, bible, _ = _cast(tmp_path)
    note = {"character_ids": ["doctor"], "location_ids": [], "concern": "presentation",
            "evidence": "Too tall", "suggestion": "Shrink"}
    other = {"character_ids": ["sailor"], "location_ids": [], "concern": "wardrobe", "evidence": "x", "suggestion": "y"}
    _review_with(config, tmp_path, bible, [note, other])

    design.dismiss_review_issue(config, tmp_path, ["doctor"], "presentation")
    status = design.review_status(config, tmp_path)
    assert status["issues"] == [other] and status["dismissed"] == 1

    # Instructions changing re-runs the review on the same pixels: still dismissed.
    path = artifacts.character_ref_instructions_path(tmp_path, "sailor")
    path.parent.mkdir(parents=True, exist_ok=True)
    artifacts.append_instruction_log_entry(path, {"instruction": "x", "patch": {"addendum": "Taller", "status": "accepted"}})
    _review_with(config, tmp_path, bible, [note])
    assert design.review_status(config, tmp_path)["issues"] == []

    # A new doctor sheet brings the note back.
    Image.new("RGB", (64, 64), "blue").save(artifacts.character_ref_sheet_path(tmp_path, "doctor"))
    _review_with(config, tmp_path, bible, [note])
    assert design.review_status(config, tmp_path)["issues"] == [note]


def test_dismiss_rejects_unknown_or_out_of_date_notes(tmp_path):
    config, bible, _ = _cast(tmp_path)
    _review_with(config, tmp_path, bible, [])
    with pytest.raises(KeyError):
        design.dismiss_review_issue(config, tmp_path, ["doctor"], "presentation")
    Image.new("RGB", (64, 64), "blue").save(artifacts.character_ref_sheet_path(tmp_path, "doctor"))
    with pytest.raises(ValueError, match="out of date"):
        design.dismiss_review_issue(config, tmp_path, ["doctor"], "presentation")


def test_review_reports_in_progress_only_during_the_model_call(tmp_path):
    config, bible, _ = _cast(tmp_path)
    seen = []

    async def response(**_kwargs):
        seen.append(design.review_status(config, tmp_path)["reviewing"])
        raise RuntimeError("provider down")

    with patch.object(design.text, "generate_json", side_effect=response):
        with pytest.raises(RuntimeError):
            asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))
    assert seen == [True]
    assert design.review_status(config, tmp_path)["reviewing"] is False


async def _produce_redrawn_reference(config, directory, redrawn):
    from novel_to_comic.asset_generation import AssetGenerationInput, compile_non_panel_request, NonPanelSubmission
    from novel_to_comic.generation_input import GenerationPromptInput
    request = compile_non_panel_request(config, AssetGenerationInput(
        asset_identity="character_ref:doctor", asset_kind="character_ref",
        prompt=GenerationPromptInput(visual_brief="A reference", width=1024, height=1024),
    ))
    with patch.object(look_assets, "submit_non_panel_request", new_callable=AsyncMock,
                      return_value=NonPanelSubmission("request", request.execution_fingerprint, redrawn)):
        outcome = await look_assets.produce_look_asset(
            config=config, project_dir=directory, request=request, output_path=redrawn.value,
            feature="cast.character_ref", force=True, refresh_review=True,
        )
    return outcome.result


def test_sheet_redraw_reruns_character_check_and_settles_its_usage(tmp_path):
    config, bible, _ = _cast(tmp_path)
    image_usage = UsageRecord(provider="test", model="img", operation="image")
    review_usage = UsageRecord(provider="test", model="txt", operation="text", input_tokens=5, output_tokens=5)

    async def review(**kwargs):
        kwargs["response_sink"](ApiResult(value="", usage=review_usage))
        return ApiResult(value={"issues": []}, usage=review_usage)

    redrawn = ApiResult(value=artifacts.character_ref_sheet_path(tmp_path, "doctor"), usage=image_usage)
    with patch.object(design.text, "generate_json", side_effect=review) as generate:
        result = asyncio.run(_produce_redrawn_reference(config, tmp_path, redrawn))
    assert generate.await_count == 1
    assert result.usage is image_usage and result.additional_usage == (review_usage,)
    assert design.review_status(config, tmp_path)["status"] == "current"


def test_failed_character_check_never_fails_the_redraw_but_still_bills(tmp_path):
    config, bible, _ = _cast(tmp_path)
    review_usage = UsageRecord(provider="test", model="txt", operation="text", input_tokens=5, output_tokens=5)

    async def review(**kwargs):
        kwargs["response_sink"](ApiResult(value="", usage=review_usage))
        return ApiResult(value={"issues": [{"character_ids": ["ghost"], "concern": "identity",
                                            "evidence": "x", "suggestion": "y"}]})

    redrawn = ApiResult(value=artifacts.character_ref_sheet_path(tmp_path, "doctor"))
    with patch.object(design.text, "generate_json", side_effect=review):
        result = asyncio.run(_produce_redrawn_reference(config, tmp_path, redrawn))
    assert result.additional_usage == (review_usage,)
    assert design.review_status(config, tmp_path)["status"] == "missing"


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


def _plate(tmp_path, bible, color="gray"):
    from types import SimpleNamespace
    bible.locations.append(SimpleNamespace(id="parlour", name="Parlour", visual_anchor="small parlour",
                                           appearance_states=[]))
    path = artifacts.location_plate_path(tmp_path, "parlour")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (96, 54), color).save(path)
    return path


def test_check_compares_sheets_and_plates_with_the_selected_proof(tmp_path):
    """Regression for drawn pages inheriting Cast's drift from the proof: a sheet
    or plate rendered off-style must be flagged at Cast, before pages are paid for."""
    config, bible, _ = _cast(tmp_path)
    plate = _plate(tmp_path, bible)
    sheet_note = {"character_ids": ["doctor"], "location_ids": [], "concern": "style",
                  "evidence": "Painterly modeled face; the proof uses flat black cut-paper silhouettes",
                  "suggestion": "Redraw as a flat black cardstock silhouette with a caricatured profile"}
    plate_note = {"character_ids": [], "location_ids": ["parlour"], "concern": "style",
                  "evidence": "Flat digital shading", "suggestion": "Use torn paper collage layers"}
    with patch.object(design, "read_cast_story_bible", return_value=bible), \
         patch.object(design.text, "generate_json", new_callable=AsyncMock,
                      return_value=ApiResult(value={"issues": [sheet_note, plate_note]})) as generate:
        asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))
        # Proof, the character contact sheet, then the plate contact sheet.
        assert len(generate.call_args.kwargs["image_attachments"]) == 3
        assert design.review_status(config, tmp_path)["issues"] == [sheet_note, plate_note]

        design.dismiss_review_issue(config, tmp_path, [], "style", ["parlour"])
        assert design.review_status(config, tmp_path)["issues"] == [sheet_note]
        # A redrawn plate makes the check out of date until Cast compares it again.
        Image.new("RGB", (96, 54), "blue").save(plate)
        assert design.review_status(config, tmp_path)["status"] == "stale"


@pytest.mark.parametrize("issue", [
    {"character_ids": [], "location_ids": ["parlour"], "concern": "wardrobe", "evidence": "x", "suggestion": "y"},
    {"character_ids": ["doctor"], "location_ids": ["parlour"], "concern": "style", "evidence": "x", "suggestion": "y"},
    {"character_ids": [], "location_ids": ["cellar"], "concern": "style", "evidence": "x", "suggestion": "y"},
])
def test_check_rejects_plate_notes_outside_style_or_known_plates(tmp_path, issue):
    config, bible, _ = _cast(tmp_path)
    _plate(tmp_path, bible)
    with patch.object(design, "read_cast_story_bible", return_value=bible), \
         patch.object(design.text, "generate_json", new_callable=AsyncMock,
                      return_value=ApiResult(value={"issues": [issue]})):
        with pytest.raises(ValueError):
            asyncio.run(design.review_cast(config, tmp_path, bible, MagicMock()))
    assert not TargetArtifacts(tmp_path).cast_review_path.exists()


def test_incompatible_artifact_requires_rerun(tmp_path):
    config, bible, _ = _cast(tmp_path)
    TargetArtifacts(tmp_path).cast_design_path.write_text(json.dumps({"schema_version": 0}))
    with pytest.raises(ArtifactInvalid, match="Rerun Cast"):
        design.read_design(config, tmp_path, bible)


def test_missing_design_rejected_before_correction_rewrite(tmp_path):
    from fastapi import HTTPException
    from novel_to_comic.server.cast_admission import apply_asset_instruction
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
        for helper in ("ensure_design", "_generate_character_refs",
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


def test_cast_visual_review_runs_after_plates_and_props(tmp_path):
    # The review is one slow model call over character sheets. Reused plates
    # and props count first, and their failures never hold the review back.
    from contextlib import ExitStack
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.state import create_initial_state

    config, bible, _ = _cast(tmp_path)
    state = create_initial_state("test", "novel.txt")
    ctx = StageRuntime("cast", state, tmp_path, on_event=lambda event: None)
    calls = []

    def helper(name):
        async def run(*args):
            calls.append(name)
            if name == "_generate_location_plates":
                ctx.record_item_failed("harbor")
        return run
    with ExitStack() as stack:
        for name in ("ensure_design", "_generate_character_refs", "_generate_character_state_refs",
                     "review_cast", "_generate_location_plates", "_generate_prop_refs"):
            stack.enter_context(patch.object(s3_cast, name, new_callable=AsyncMock, side_effect=helper(name)))
        with pytest.raises(ValueError, match="Resume Cast"):
            asyncio.run(s3_cast.run(config, tmp_path, ctx))
    assert calls[-3:] == ["_generate_location_plates", "_generate_prop_refs", "review_cast"]
    assert "cast_visual_review" not in state.stages["cast"].items_failed


@pytest.mark.parametrize("provider_error,held_after", [
    ("image_tool_failed: the request was likely silently rejected by the provider's safety system", 1),
    ("image_tool_failed", 2),
])
def test_cast_resume_holds_unchanged_state_request_that_keeps_failing(tmp_path, monkeypatch, provider_error, held_after):
    from novel_to_comic.models.story_bible import AppearanceState
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.state import create_initial_state

    config, bible, _ = _cast(tmp_path)
    bible.characters[0].appearance_states = [AppearanceState(
        id="bare", label="Suit gone", visual_anchor="naked, no spacesuit", visually_significant=True,
        changed_facets=("clothing",))]
    artifacts.write_story_bible(tmp_path, bible)
    submissions = []

    async def refuse(**kwargs):
        submissions.append(kwargs["output_path"])
        raise RuntimeError(provider_error)

    monkeypatch.setattr("novel_to_comic.asset_generation.execute_frozen_request", refuse)

    def resume():
        ctx = StageRuntime("cast", create_initial_state("test", "novel.txt"), tmp_path, on_event=lambda _: None)
        asyncio.run(s3_cast._generate_character_state_refs(
            config, tmp_path, bible, ctx, style_ref=tmp_path / "samples/style_1.png"))
        return ctx.stage_state

    for _ in range(held_after):
        stage = resume()
        assert stage.items_failed == ["sailor:bare"]
    assert len(submissions) == held_after
    stage = resume()
    assert stage.items_failed == ["sailor:bare"]
    assert len(submissions) == held_after  # held: the unchanged request is not resubmitted

    [failure] = s3_cast.cast_failure_details(tmp_path, stage)
    assert failure["label"] == "Gustaf — Suit gone"
    assert failure["attempts"] == held_after
    if held_after == 1:
        assert failure["classification"] == "provider_blocked"
        assert failure["message"] == s3_cast.CAST_BLOCKED_MESSAGE
        assert "scene" not in failure["message"] and "page" not in failure["message"]
        assert "less graphic version" in s3_cast.cast_approval_blocker(config, tmp_path, stage)
        assert [(item["phrase"], item["category"], item["source"]) for item in failure["likely_triggers"]] == [
            ("naked", "nudity", "description")]
    else:
        assert failure["likely_triggers"] == []

    # Changing the direction yields a new request, which Resume submits again.
    bible.characters[0].appearance_states[0].visual_anchor = "no spacesuit, wrapped in a blanket"
    resume()
    assert len(submissions) == held_after + 1


def test_successful_asset_clears_stale_failure_sidecar(tmp_path, monkeypatch):
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.state import create_initial_state

    config, bible, _ = _cast(tmp_path)
    sheet = artifacts.character_ref_sheet_path(tmp_path, "sailor")
    sheet.unlink()
    artifacts.write_asset_failure(sheet, {"classification": "timed_out"})

    async def draw(**kwargs):
        Image.new("RGB", (64, 64), "blue").save(kwargs["output_path"])
        return ApiResult(value=kwargs["output_path"])

    monkeypatch.setattr("novel_to_comic.asset_generation.execute_frozen_request", draw)
    monkeypatch.setattr(s3_cast, "_crop_sheet_to_poses", lambda path: None)
    ctx = StageRuntime("cast", create_initial_state("test", "novel.txt"), tmp_path, on_event=lambda _: None)
    asyncio.run(s3_cast._generate_character_refs(
        config, tmp_path, bible, ctx, ["sailor"], tmp_path / "samples/style_1.png"))
    assert sheet.is_file()
    assert not artifacts.asset_failure_path(sheet).exists()


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
        blocker = s3_cast.cast_approval_blocker(config, tmp_path, stage)
        assert blocker.startswith("Gustaf — Altered appearance:")
        assert "Resume Cast" in blocker


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
    assert "Resume Cast" in blocker
    assert [failure["item_id"] for failure in status["stages"]["cast"]["failures"]] == ["sailor:alternate"]
    with pytest.raises(HTTPException) as error:
        asyncio.run(pipeline.approve("cast", "test", request, (tmp_path, config, state), "account"))
    assert error.value.status_code == 409
    assert error.value.detail == {"code": "cast_approval_rejected", "message": blocker}
    assert state.stages["cast"].status == StageStatus.AWAITING_REVIEW


def test_missing_cast_source_is_a_blocker_not_a_status_read_failure(tmp_path):
    from novel_to_comic.config import Config
    from novel_to_comic.state import StageState
    assert "source artifacts" in s3_cast.cast_approval_blocker(Config(), tmp_path, StageState())


@pytest.mark.parametrize("invalid_first", [False, True])
def test_a_new_character_is_designed_beside_the_established_cast(tmp_path, invalid_first):
    config, bible, plan = _cast(tmp_path)
    bible.characters.append(bible.characters[0].model_copy(update={
        "id": "cook", "name": "Cook", "visual_anchor": "adult female, red apron"}))
    requests = []

    async def respond(**kwargs):
        requests.append(kwargs["user_content"])
        assert TargetArtifacts(tmp_path).read_cast_design() == plan
        schema = kwargs["json_schema"]
        assert schema["properties"]["characters"]["minItems"] == 1
        assert schema["properties"]["characters"]["maxItems"] == 1
        assert schema["$defs"]["CharacterDesign"]["properties"]["character_id"]["enum"] == ["cook"]
        new_design = {
            "character_id": "cook", "face": "round face", "hair": "bun", "silhouette": "short",
            "posture": "busy", "wardrobe": "apron", "contrast": "Unlike Gustaf and the Doctor"}
        characters = [new_design]
        if invalid_first and len(requests) == 1:
            characters.append({**plan.characters[0].model_dump(), "face": "replaced established face"})
        return ApiResult(value={"characters": characters})

    with patch.object(design.text, "generate_json", side_effect=respond):
        updated = asyncio.run(design.ensure_design(config, tmp_path, bible, MagicMock()))

    assert len(requests) == (2 if invalid_first else 1)
    request = json.loads(requests[0])
    assert [c["character_id"] for c in request["characters"]] == ["cook"]
    assert {d["character_id"] for d in request["established"]} == {"sailor", "doctor"}
    assert updated.characters[:2] == plan.characters
    assert updated.fingerprints["sailor"] == plan.fingerprints["sailor"]
    assert design.read_design(config, tmp_path, bible).characters[2].face == "round face"


def test_renaming_or_relating_a_character_keeps_its_design(tmp_path):
    config, bible, plan = _cast(tmp_path)
    bible.characters[0].name = "Gustaf the Elder"
    bible.characters[0].relationships = [{"character_id": "doctor", "relationship": "friend"}]
    assert design.read_design(config, tmp_path, bible).characters == plan.characters


def test_a_current_whole_roster_plan_is_converted_once_without_changing_designs(tmp_path):
    config, bible, plan = _cast(tmp_path)
    path = TargetArtifacts(tmp_path).cast_design_path
    earlier = {"schema_version": 1, "source_sha256": design._digest(design.design_context(config, bible)),
               "characters": [c.model_dump() for c in plan.characters]}
    path.write_text(json.dumps(earlier))

    assert design.read_design(config, tmp_path, bible).characters == plan.characters
    assert json.loads(path.read_text())["schema_version"] == 2

    path.write_text(json.dumps({**earlier, "source_sha256": "0" * 64}))
    assert design.current_designs(config, tmp_path, bible) == {}


def test_design_request_carries_story_evidence_for_unspecified_details(tmp_path):
    """Regression for DCC's Mordecai: appearance facts alone gave the designer no
    age or temperament, and it mirrored another character's open top."""
    from novel_to_comic.models.story_bible import Scene

    config, bible, _ = _project(tmp_path, "image-gemini-pro")
    bible.characters[0].baseline_affect = "weary"
    bible.scenes = [Scene.model_construct(
        id=f"scene_{n}", character_ids=["sailor"],
        summary=f"The storm breaks. Gustaf drinks alone, night {n}. The ship creaks.",
    ) for n in range(1, 9)]
    request = design._design_request(config, bible, {"sailor"}, {})

    sailor = request["characters"][0]
    assert sailor["baseline_affect"] == "weary"
    assert sailor["story_evidence"] == [f"Gustaf drinks alone, night {n}." for n in range(1, 7)]
    assert "story_evidence" not in design.design_context(config, bible)["characters"][0]
    assert "never leave a chest, torso,\nskin or fur exposed under it" in design.DESIGN_SYSTEM
    assert "Differentiate wardrobe as deliberately as faces" in design.DESIGN_SYSTEM


def test_character_sheet_states_gender_and_shows_unusual_stature_to_scale(tmp_path):
    config, bible, plan = _cast(tmp_path)
    character = bible.characters[0]
    ordinary = s3_cast._character_generation_input(config, bible, character, design=plan).prompt.constraints
    assert f"Canonical gender: {character.gender}." in ordinary
    assert "Canonical stature" not in ordinary

    small = character.model_copy(update={"stature": "two and a half feet tall"})
    constraints = s3_cast._character_generation_input(config, bible, small, design=plan).prompt.constraints
    assert "Canonical stature: two and a half feet tall." in constraints
    assert "silhouette of an ordinary adult" in constraints


def test_dismiss_route_returns_the_filtered_check_and_maps_errors(tmp_path):
    from fastapi import HTTPException
    from novel_to_comic.server.routers.cast_assets import DismissReviewNoteRequest, dismiss_cast_review_note
    config, bible, _ = _cast(tmp_path)
    note = {"character_ids": ["doctor"], "location_ids": [], "concern": "presentation",
            "evidence": "Too tall", "suggestion": "Shrink"}
    _review_with(config, tmp_path, bible, [note])
    body = DismissReviewNoteRequest(character_ids=["doctor"], concern="presentation")
    status = dismiss_cast_review_note(body, (tmp_path, config, None), "user")
    assert status["issues"] == [] and status["dismissed"] == 1
    with pytest.raises(HTTPException) as missing:
        dismiss_cast_review_note(DismissReviewNoteRequest(character_ids=["sailor"], concern="wardrobe"),
                                 (tmp_path, config, None), "user")
    assert missing.value.status_code == 404


def test_only_main_sheet_redraws_carry_the_character_check():
    from novel_to_comic.server.codex_admission import cast_asset_operations, visual_review_operations
    config = MagicMock()
    config.effective_image_model.return_value = "img"
    config.effective_visual_review_model.return_value = "vision"
    assert cast_asset_operations(config, "character_ref_regen", "doctor")[-1] == visual_review_operations(config)[0]
    assert cast_asset_operations(config, "character_ref_regen", "doctor:burned") == (("image", "img"),)
    assert cast_asset_operations(config, "prop_ref_regen", "key") == (("image", "img"),)
    # Canonical plates are compared with the proof too; state plates are not.
    assert cast_asset_operations(config, "location_plate_regen", "parlour")[-1] == visual_review_operations(config)[0]
    assert cast_asset_operations(config, "location_plate_regen", "parlour:flooded") == (("image", "img"),)

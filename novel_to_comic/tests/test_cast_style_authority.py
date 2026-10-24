"""Regression for project 47ce4ed9: lost style and cloned lineup identities."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from novel_to_comic import look_assets
from novel_to_comic.asset_generation import NonPanelSubmission
from novel_to_comic.asset_generation import compile_non_panel_request, style_reference_plan
from novel_to_comic.config import Config
from novel_to_comic.models.appearance import AppearanceState
from novel_to_comic.models.story_bible import Character, StoryBible
from novel_to_comic.stages import s3_cast
from novel_to_comic.style_contract import style_template_for_suggestion
from novel_to_comic.usage import ApiResult

from .style_reference_support import write_location_style_board


def _save_design(config, project_dir, bible):
    from novel_to_comic.cast_design import CastDesignPlan, CharacterDesign, character_fingerprint
    from novel_to_comic.target_artifacts import TargetArtifacts
    plan = CastDesignPlan(characters=[
        CharacterDesign(character_id=c.id, face=f"{c.id} facial landmarks", hair="source hair",
                        silhouette="source anatomy", posture="resting", wardrobe="source wardrobe",
                        contrast="Distinct from the rest of the cast") for c in bible.characters],
        fingerprints={c.id: character_fingerprint(config, c) for c in bible.characters})
    TargetArtifacts(project_dir).write_cast_design(plan)
    return plan


def _project(tmp_path, model):
    suggestion = {"template": "Follow this sample's rough ink and ochre palette."}
    config = Config(image_model=model, style_template=style_template_for_suggestion(suggestion))
    bible = StoryBible(title="Voyage", author="Test", total_scenes=0, characters=[Character(
        id="sailor", name="Gustaf", visual_anchor="adult male, yellow hair, sailor",
        age_range="30s", gender="male", distinguishing_features=["yellow hair"],
        default_outfit="seaman's working clothes", first_appearance_scene="scene_1",
    )], locations=[], scenes=[], sequences=[])
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples/style_suggestions.json").write_text(json.dumps({"suggestions": [suggestion]}))
    proof = tmp_path / "samples/style_1.png"
    Image.new("RGB", (32, 40), "orange").save(proof)
    return config, bible, proof


@pytest.mark.parametrize("model", ["image-sunburst", "image-flare", "image-gemini-pro"])
def test_cast_wire_keeps_approved_style_and_canonical_identity(tmp_path, model):
    config, bible, proof = _project(tmp_path, model)
    style = s3_cast._cast_asset_style_ref(config, s3_cast._find_style_ref(tmp_path, config.style_template))
    assert style == proof
    request = compile_non_panel_request(
        config, s3_cast._character_generation_input(config, bible, bible.characters[0]),
        reference_plan=style_reference_plan(config, style),
    )
    assert request.reference_plan.selected[0].path == proof
    prompt = request.compiled.final_prompt
    assert bible.characters[0].visual_anchor in prompt
    assert "Canonical age: 30s" in prompt
    assert "seaman's working clothes" in prompt
    assert "do not copy their faces" in prompt
    assert "sole visual rendering style authority" in prompt
    assert "facial abstraction" in prompt
    assert "poses, gaze, expressions, camera angles" in prompt
    assert "Transfer how faces and bodies are drawn" in prompt
    assert "surface-fidelity constraints" in prompt
    assert "do not treat every blotch, stain or speckle as an authored style feature" in prompt
    assert "match its exact" not in prompt
    assert "overrides any conflict" not in prompt
    # The written style is primary: a demoted text let sheets drop the
    # selected character design, and every Draw page inherited that drift.
    assert "Secondary" not in prompt
    assert "apply this written direction in full, including its character design" in prompt
    assert "the style's intended caricature, exaggeration or simplification is required" in prompt
    assert "LETTERING STANDARD" not in prompt


@pytest.mark.parametrize("model", ["image-sunburst", "image-gemini-pro", "image-gemini-flash-lite", "image-gpt-2", "image-flare"])
def test_all_models_use_original_proof_through_run_resume_and_estimate(tmp_path, model):
    config, bible, proof = _project(tmp_path, model)
    board = tmp_path / "refs" / "character_style_board.png"
    board.parent.mkdir()
    Image.new("RGB", (32, 40), "gray").save(board)
    with patch.object(s3_cast, "asset_matches_request", return_value=True) as matches:
        assert s3_cast._character_style_reference(config, tmp_path, proof) == proof
    matches.assert_not_called()
    ctx = MagicMock()
    ctx.stage_state.items_failed = []
    with (
        patch.object(s3_cast, "ensure_design", new_callable=AsyncMock),
        patch.object(s3_cast, "review_cast", new_callable=AsyncMock),
        patch.object(s3_cast, "_generate_character_refs", new_callable=AsyncMock) as canonical,
        patch.object(s3_cast, "_generate_character_state_refs", new_callable=AsyncMock) as states,
    ):
        asyncio.run(s3_cast.run(config, tmp_path, ctx, char_ids=["sailor"]))
    ctx.execute.assert_called_once_with(total=3)
    assert canonical.await_args.args[-1] == proof
    assert states.await_args.args[-1] == proof
    board.unlink()
    with patch("novel_to_comic.asset_generation.estimate_non_panel_request") as estimate:
        estimate.return_value.cost_usd = .03
        s3_cast.estimate_cost(config, tmp_path, MagicMock())
    assert {call.args[1].asset_kind for call in estimate.call_args_list} == {"character_ref"}


@pytest.mark.parametrize("model", ["image-sunburst", "image-gemini-pro"])
def test_human_animal_creature_and_state_share_same_rendering_authority(tmp_path, model):
    config, bible, proof = _project(tmp_path, model)
    for identity, anchor in (("cat", "tortoiseshell cat, four legs, amber eyes"),
                             ("creature", "winged creature, green scales, two claws")):
        bible.characters.append(Character(id=identity, name=identity, visual_anchor=anchor,
            age_range="adult", gender="unknown", distinguishing_features=[],
            default_outfit="none", first_appearance_scene="scene_1"))
    bible.characters[0].appearance_states = [AppearanceState(
        id="white_hair", label="White hair", visual_anchor="adult male, white hair, sailor",
        changed_facets=("hair",), visually_significant=True,
    )]
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    board = tmp_path / "refs" / "character_style_board.png"
    board.parent.mkdir()
    Image.new("RGB", (32, 40), "gray").save(board)
    expected = proof
    _save_design(config, tmp_path, bible)
    requests = []

    async def submit(**kwargs):
        requests.append(kwargs["request"])
        Image.new("RGB", (32, 32), "blue").save(kwargs["output_path"])
        return NonPanelSubmission("test", kwargs["request"].execution_fingerprint, result=ApiResult(value=kwargs["output_path"]))

    async def generate():
        for char in bible.characters:
            await s3_cast.regenerate_character_ref(config, tmp_path, char.id)
        await s3_cast.regenerate_character_state_ref(config, tmp_path, "sailor", "white_hair")

    with patch.object(s3_cast, "asset_matches_request", return_value=True), \
         patch.object(look_assets, "submit_non_panel_request", side_effect=submit):
        asyncio.run(generate())
    style_hashes = set()
    for request in requests[:-1]:
        styles = [ref for ref in request.reference_plan.selected if ref.role == "style"]
        assert len(styles) == 1 and styles[0].path == expected
        style_hashes.add(styles[0].content_sha256)
        assert "one artistic hand across the entire cast" in request.compiled.final_prompt
        assert "sole visual rendering style authority" in request.compiled.final_prompt
    assert len(style_hashes) == 1
    # The look's style authority is its main sheet, which the proof styled.
    state_refs = requests[-1].reference_plan.selected
    assert [ref.role for ref in state_refs] == ["subject"] and state_refs[0].entity_id == "sailor"
    assert "rendering style authority" in requests[-1].compiled.final_prompt
    for char, request in zip(bible.characters, requests):
        assert char.visual_anchor in request.compiled.final_prompt


def test_sunburst_cannot_silently_fall_back_to_text_only_cast(tmp_path):
    config, bible, proof = _project(tmp_path, "image-sunburst")
    proof.unlink()
    with patch.object(look_assets, "submit_non_panel_request", new_callable=AsyncMock) as submit:
        with pytest.raises(ValueError, match="selected Style proof is missing"):
            asyncio.run(s3_cast.regenerate_character_ref(config, tmp_path, "sailor"))
        with pytest.raises(ValueError, match="selected Style proof is missing"):
            asyncio.run(s3_cast._generate_character_refs(config, tmp_path, bible, MagicMock()))
    submit.assert_not_awaited()


def test_location_plate_frames_the_place_at_its_true_scale_without_the_style_proof(tmp_path):
    """Regression for repeated tavern plates and a guild hall cloned from the
    proof's apartment: the proof's room carried into other locations, and a
    fixed wide shot let small or sparse anchors grow into it. Text alone then
    lost the proof's rendering, so plates take it from a room-free board."""
    config, _bible, proof = _project(tmp_path, "image-sunburst")
    board = write_location_style_board(config, tmp_path)
    anchor = "tiny wood-paneled booth room with sliding pocket-door"
    location = SimpleNamespace(id="loc_snug", name="Snug", visual_anchor=anchor)
    request = compile_non_panel_request(
        config, s3_cast._location_generation_input(config, location),
        reference_plan=s3_cast._location_plate_reference_plan(config, board),
    )
    prompt = request.compiled.final_prompt
    assert [ref.path for ref in request.reference_plan.selected] == [board]
    assert proof not in [ref.path for ref in request.reference_plan.selected]
    assert s3_cast.LOCATION_STYLE_BOARD_LABEL in prompt
    assert "Secondary" not in prompt and "rough ink and ochre palette" in prompt
    assert anchor in prompt
    assert "framed at the location's true scale and enclosure" in prompt
    # The whole brief survives text-safety hygiene (it strips "read as ..." clauses).
    assert s3_cast._LOCATION_PLATE_DIRECTION in prompt
    assert "wide environment design plate" not in prompt.lower()


@pytest.mark.parametrize(("form", "identity_kind", "expected"), [
    ("form", "individual", "never invent a back, head or limbs the anchor does not give it"),
    ("formation", "group", "with the member count and arrangement the anchor gives"),
])
def test_non_figure_sheets_drop_the_turnaround(tmp_path, form, identity_kind, expected):
    """Labs 2026-10-04: a turnaround drew one planet-sized heart five times and
    invented a back view for a floating eye."""
    from novel_to_comic import reference_forms

    config, bible, proof = _project(tmp_path, "image-sunburst")
    hearts = Character(
        id="hearts", name="Cosmic Hearts", visual_anchor="trio of planet-sized anatomical hearts",
        age_range="", gender="", distinguishing_features=[], default_outfit="",
        first_appearance_scene="scene_1", identity_kind=identity_kind, reference_form=form,
    )
    request = compile_non_panel_request(
        config, s3_cast._character_generation_input(config, bible, hearts),
        reference_plan=style_reference_plan(config, proof),
    )
    prompt = request.compiled.final_prompt
    assert expected in prompt
    assert "no props, vehicles, scenery or story situation" in prompt
    assert "turnaround" not in prompt and "back view" not in prompt
    assert "relaxed neutral expression" not in prompt
    assert reference_forms.IDENTITY_DESIGN[form] in prompt
    assert hearts.visual_anchor in prompt


def test_a_state_can_change_the_sheet_form_and_figure_states_keep_theirs(tmp_path):
    from novel_to_comic import reference_forms
    from novel_to_comic.state_assets import build_character_state_spec

    config, bible, proof = _project(tmp_path, "image-sunburst")
    sailor = bible.characters[0]
    mist = AppearanceState(id="mist", label="Mist", visual_anchor="drifting grey mist with yellow-haired face",
                           changed_facets=("anatomy",), visually_significant=True, reference_form="form")
    plain = AppearanceState(id="wet", label="Wet", visual_anchor="adult male, wet yellow hair, sailor",
                            changed_facets=("hair",), visually_significant=True)
    assert build_character_state_spec(config, tmp_path, sailor, mist).reference_form == "form"
    assert reference_forms.STATE_DIRECTION["form"] in build_character_state_spec(
        config, tmp_path, sailor, mist).rendered_prompt
    figure = build_character_state_spec(config, tmp_path, sailor, plain)
    assert figure.reference_form == "figure"
    assert reference_forms.STATE_DIRECTION["figure"] in figure.rendered_prompt


def test_formation_is_only_for_groups():
    with pytest.raises(ValueError, match="only for identity_kind 'group'"):
        Character(id="eye", name="Eye", visual_anchor="giant eye", age_range="", gender="",
                  distinguishing_features=[], default_outfit="", first_appearance_scene="s",
                  reference_form="formation")


def test_only_figures_receive_the_character_proportion_system(tmp_path):
    """Regression for The Last Question: "squared cleft jaws" and facial-identity
    wording gave a form sheet for a point of light a technician's face."""
    from novel_to_comic import reference_forms

    config, bible, proof = _project(tmp_path, "image-sunburst")
    suggestion = {"template": "Matte gouache on warm board.", "visual_logic": "realistic_illustration",
                  "proportion_family": "heroic", "character_design": "Squared cleft jaws."}
    config = config.model_copy(update={"style_template": style_template_for_suggestion(suggestion)})
    light = Character(
        id="light", name="Last Mind", visual_anchor="solitary fading point of mental light",
        age_range="", gender="", distinguishing_features=[], default_outfit="",
        first_appearance_scene="scene_1", reference_form="form",
    )
    prompts = {
        name: compile_non_panel_request(config, input_data, reference_plan=plan).compiled.final_prompt
        for name, input_data, plan in (
            ("figure", s3_cast._character_generation_input(config, bible, bible.characters[0]),
             style_reference_plan(config, proof)),
            ("form", s3_cast._character_generation_input(config, bible, light),
             style_reference_plan(config, proof)),
            ("plate", s3_cast._location_generation_input(
                config, SimpleNamespace(id="loc", name="Void", visual_anchor="black void")),
             s3_cast._location_plate_reference_plan(config, proof)),
        )
    }
    assert "Squared cleft jaws." in prompts["figure"]
    assert reference_forms.IDENTITY_QUALITY["figure"] in prompts["figure"]
    for name in ("form", "plate"):
        assert "Matte gouache on warm board." in prompts[name]
        assert "Squared cleft jaws." not in prompts[name]
    assert reference_forms.IDENTITY_QUALITY["form"] in prompts["form"]
    assert "facial identity" not in prompts["form"]
    assert "light or face" not in prompts["form"]


def test_location_style_board_carries_the_proof_rendering_without_its_scene(tmp_path):
    config, _bible, proof = _project(tmp_path, "image-sunburst")
    request = s3_cast._location_style_board_request(config, tmp_path, proof)
    prompt = request.compiled.final_prompt
    assert request.compiled.asset_kind == "style_calibration"
    assert [ref.path for ref in request.reference_plan.selected] == [proof]
    assert "rooms, interiors, architecture, furniture, landscapes, scenery" in prompt
    assert "Do not reproduce any recognizable subject, room or object from the reference" in prompt
    assert "rough ink and ochre palette" in prompt
    # A changed proof makes the board, and so every plate, out of date.
    board = write_location_style_board(config, tmp_path)
    Image.new("RGB", (32, 40), "purple").save(proof)
    assert s3_cast._location_style_board(config, tmp_path) is None
    with pytest.raises(ValueError, match="location style board is missing or out of date"):
        s3_cast._require_location_style_board(config, tmp_path)
    assert board.exists()


def test_plate_redraw_requires_a_current_board_before_spending(tmp_path):
    config, bible, _proof = _project(tmp_path, "image-sunburst")
    from novel_to_comic.models.story_bible import Location
    bible.locations.append(Location(id="snug", name="Snug", visual_anchor="tiny booth room", mood="quiet"))
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    with patch.object(look_assets, "submit_non_panel_request", new_callable=AsyncMock) as submit:
        with pytest.raises(ValueError, match="Resume Cast to prepare it"):
            asyncio.run(s3_cast.regenerate_location_plate(config, tmp_path, "snug"))
    submit.assert_not_awaited()


@pytest.mark.parametrize("board_fails", [False, True])
def test_cast_prepares_the_board_before_plates_and_plates_wait_for_it(tmp_path, board_fails):
    from contextlib import ExitStack
    from novel_to_comic.models.story_bible import Location
    from novel_to_comic.stage_runtime import StageRuntime
    from novel_to_comic.state import create_initial_state

    config, bible, _proof = _project(tmp_path, "image-sunburst")
    bible.locations.append(Location(id="snug", name="Snug", visual_anchor="tiny booth room", mood="quiet"))
    (tmp_path / "story_bible.json").write_text(bible.model_dump_json())
    ctx = StageRuntime("cast", create_initial_state("test", "novel.txt"), tmp_path, on_event=lambda event: None)
    plate_wires = []

    async def submit(**kwargs):
        if kwargs["feature"] == "cast.location_style_board" and board_fails:
            raise RuntimeError("provider down")
        output = kwargs["output_path"]
        output.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (48, 27), "gray").save(output)
        if kwargs["feature"] == "cast.location_plate":
            plate_wires.append(kwargs["request"])
        return NonPanelSubmission("test", kwargs["request"].execution_fingerprint, result=ApiResult(value=output))

    with ExitStack() as stack:
        stack.enter_context(patch.object(look_assets, "submit_non_panel_request", side_effect=submit))
        stack.enter_context(patch.object(s3_cast, "asset_matches_request",
                                         side_effect=lambda path, _request: False))
        stack.enter_context(patch.object(s3_cast, "_location_style_board",
                                         return_value=None if board_fails else s3_cast._location_style_board_path(tmp_path)))
        for name in ("ensure_design", "_generate_character_refs", "_generate_character_state_refs",
                     "review_cast", "_generate_prop_refs"):
            stack.enter_context(patch.object(s3_cast, name, new_callable=AsyncMock))
        if board_fails:
            with pytest.raises(ValueError, match="Location style board"):
                asyncio.run(s3_cast.run(config, tmp_path, ctx, loc_ids=["snug"]))
            assert plate_wires == []
            return
        asyncio.run(s3_cast.run(config, tmp_path, ctx, loc_ids=["snug"]))
    board = s3_cast._location_style_board_path(tmp_path)
    assert [[ref.path for ref in wire.reference_plan.selected] for wire in plate_wires] == [[board]]

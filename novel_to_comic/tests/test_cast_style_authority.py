"""Regression for project 47ce4ed9: lost style and cloned lineup identities."""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from novel_to_comic.asset_generation import compile_non_panel_request, style_reference_plan
from novel_to_comic.config import Config
from novel_to_comic.models.appearance import AppearanceState
from novel_to_comic.models.story_bible import Character, StoryBible
from novel_to_comic.stages import s3_cast
from novel_to_comic.style_contract import style_template_for_suggestion
from novel_to_comic.usage import ApiResult


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
    )], locations=[], scenes=[], narrative_arcs=[])
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
        return SimpleNamespace(result=ApiResult(value=kwargs["output_path"]))

    async def generate():
        for char in bible.characters:
            await s3_cast.regenerate_character_ref(config, tmp_path, char.id)
        await s3_cast.regenerate_character_state_ref(config, tmp_path, "sailor", "white_hair")

    with patch.object(s3_cast, "asset_matches_request", return_value=True), \
         patch.object(s3_cast, "submit_non_panel_request", side_effect=submit):
        asyncio.run(generate())
    style_hashes = set()
    for request in requests:
        styles = [ref for ref in request.reference_plan.selected if ref.role == "style"]
        assert len(styles) == 1 and styles[0].path == expected
        style_hashes.add(styles[0].content_sha256)
        assert "one artistic hand across the entire cast" in request.compiled.final_prompt
        assert "sole visual rendering style authority" in request.compiled.final_prompt
    assert len(style_hashes) == 1
    state_subjects = [ref for ref in requests[-1].reference_plan.selected if ref.role == "subject"]
    assert len(state_subjects) == 1 and state_subjects[0].entity_id == "sailor"
    for char, request in zip(bible.characters, requests):
        assert char.visual_anchor in request.compiled.final_prompt


def test_sunburst_cannot_silently_fall_back_to_text_only_cast(tmp_path):
    config, bible, proof = _project(tmp_path, "image-sunburst")
    proof.unlink()
    with patch.object(s3_cast, "submit_non_panel_request", new_callable=AsyncMock) as submit:
        with pytest.raises(ValueError, match="selected Style proof is missing"):
            asyncio.run(s3_cast.regenerate_character_ref(config, tmp_path, "sailor"))
        with pytest.raises(ValueError, match="selected Style proof is missing"):
            asyncio.run(s3_cast._generate_character_refs(config, tmp_path, bible, MagicMock()))
    submit.assert_not_awaited()

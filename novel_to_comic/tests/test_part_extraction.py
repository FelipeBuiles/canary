"""A later part extracts against the series Story Bible; its Brief inherits direction."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from novel_to_comic import artifacts
from novel_to_comic import extraction_sections as sections
from novel_to_comic.briefing import build_brief_inference_prompt, propose_brief
from novel_to_comic.config import Config
from novel_to_comic.models.adaptation import AdaptationBrief
from novel_to_comic.models.story_bible import ExcludedEntity, MissingVisualAnchor
from novel_to_comic.series import append_parts, initialize_series, read_extraction_delta, replace_part_text
from novel_to_comic.source_extraction import source_units
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.stages import s1_extract
from novel_to_comic.state import load_state
from novel_to_comic.target_artifacts import TargetArtifacts
from novel_to_comic.usage import ApiResult, UsageRecord
from novel_to_comic.workspace import part_workspace

PART_ONE = "".join(f"Ari crossed gate number {i}. " for i in range(220))
PART_TWO = "".join(f"Ari met the ferryman at dock {i}. " for i in range(60))


def _section_payload(content: dict, *, newcomer: str | None = None) -> dict:
    prefix = content["id_prefix"]
    scene_id = prefix + "scene_001"
    registry = {entry["id"] for entry in content.get("registry", {}).get("characters", [])}
    ari = "part0001_char_001"
    characters = []
    locations = []
    if ari in registry:
        characters.append({"id": ari})
    else:
        characters.append({
            "id": ari, "name": "Ari", "visual_anchor": "1woman, adult female, black hair",
            "age_range": "adult", "gender": "female", "distinguishing_features": [],
            "default_outfit": "coat", "first_appearance_scene": scene_id,
        })
    roster = [ari]
    participation = [{"character_id": ari, "scene_id": scene_id,
                      "classification": "direct_action", "source_quote": "Ari"}]
    if newcomer:
        characters.append({
            "id": prefix + "char_001", "name": newcomer, "visual_anchor": "1man, adult male, beard",
            "age_range": "old", "gender": "male", "distinguishing_features": [],
            "default_outfit": "oilskin", "first_appearance_scene": scene_id,
        })
        roster.append(prefix + "char_001")
        participation.append({"character_id": prefix + "char_001", "scene_id": scene_id,
                              "classification": "direct_action", "source_quote": "Ari"})
    location_id = prefix + "loc_001"
    locations.append({"id": location_id, "name": f"Place {prefix}", "visual_anchor": "stone", "mood": "quiet"})
    return {
        "title": "Crossing", "author": "Unknown", "total_scenes": 1,
        "characters": characters, "locations": locations, "props": [], "sequences": [],
        "scenes": [{
            "id": scene_id, "chapter": 1, "title": "Scene", "location_id": location_id,
            "character_ids": roster, "summary": "Ari keeps going.", "scene_type": "action",
            "narrative_beat": "rising_action",
            "source_start_quote": source_units(content["source_section"])[0].text.strip(),
        }],
        "character_participation": participation,
    }


def _fake_model(monkeypatch, *, newcomer: str | None = None, title: str = "Crossing"):
    calls = []

    async def generate(**kwargs):
        content = json.loads(kwargs["user_content"])
        if kwargs["feature"].startswith("extract.book_map"):
            calls.append(kwargs["feature"])
            value = _book_map_response(kwargs["feature"], content)
        elif kwargs["feature"] == "extract.sequences":
            ids = [scene["id"] for scene in content["scenes"]]
            value = {"title": title, "author": "Unknown", "sequences": [
                {"number": act, "title": f"Act {act}", "scenes": ids if act == 1 else []} for act in (1, 2, 3)]}
        else:
            calls.append(content["id_prefix"])
            value = _section_payload(content, newcomer=newcomer)
        return ApiResult(value=value, usage=UsageRecord(provider="test", model="test", operation="text", cost_usd=0))

    monkeypatch.setattr(sections, "generate_json", generate)
    monkeypatch.setattr(s1_extract, "generate_json", generate)
    return calls


def _book_map_response(feature: str, content: dict) -> dict:
    if feature == "extract.book_map_digest":
        return {"synopsis": "Ari keeps crossing.", "characters": [
            {"name": "Ari", "aliases": [], "role": "traveller", "presence": "central"}]}
    parts = [part["part_id"] for part in content["parts"]]
    return {
        "synopsis": "Ari crosses the river with a ferryman's help.",
        "acts": [{"number": 1, "title": "The crossing", "summary": "Ari crosses.",
                  "first_part": parts[0], "last_part": parts[-1]}],
        "parts": [{"part_id": part, "role": f"Stage {index} of the crossing"} for index, part in enumerate(parts, 1)],
        "characters": [{"name": "Ferryman", "aliases": [], "role": "guide", "prominence": "recurring",
                        "first_part": parts[-1], "last_part": parts[-1]}],
    }


def _series(tmp_path: Path) -> Path:
    root = tmp_path / "book"
    root.mkdir()
    (root / "input").mkdir()
    (root / "input" / "novel.txt").write_text(PART_ONE)
    initialize_series(root, project_name="Crossing", novel_path=root / "input" / "novel.txt", text=PART_ONE)
    append_parts(root, [("Part 2", PART_TWO)])
    return root


def _extract(root: Path, part: str, config: Config):
    workspace = part_workspace(root, part)
    ctx = StageRuntime("extract", load_state(workspace), workspace)
    return asyncio.run(s1_extract.run(config, workspace, ctx))


def test_a_later_part_continues_ids_ordinals_and_sequences(tmp_path, monkeypatch) -> None:
    root = _series(tmp_path)
    # Part 1 is long enough to extract in sections; part 2 always uses them.
    config = Config(extraction_chunk_chars=4000)
    calls = _fake_model(monkeypatch, newcomer=None)
    _extract(root, "part_0001", config)
    calls_two = _fake_model(monkeypatch, newcomer="Ferryman", title="Ignored Retitle")
    bible = _extract(root, "part_0002", config)

    # Part 1 maps the whole saved book once; part 2 reuses the fresh map.
    assert calls[:3] == ["extract.book_map_digest", "extract.book_map_digest", "extract.book_map"]
    assert calls[3:] and all(prefix.startswith("part") for prefix in calls[3:])
    assert calls_two and all(prefix.startswith("p0002s") for prefix in calls_two)
    # The book map names the ferryman recurring, so Cast designs him.
    assert next(c for c in bible.characters if c.name == "Ferryman").cast_required
    assert bible.title == "Crossing"
    assert {scene.part_id for scene in bible.scenes} == {"part_0001", "part_0002"}
    ari = [character for character in bible.characters if character.id == "part0001_char_001"]
    assert len(ari) == 1 and ari[0].name == "Ari"
    assert any(character.name == "Ferryman" for character in bible.characters)
    assert {arc.part_id for arc in bible.sequences} == {"part_0001", "part_0002"}
    assert artifacts.read_story_bible(root) == bible

    first = TargetArtifacts(part_workspace(root, "part_0001")).read_source()
    second = TargetArtifacts(part_workspace(root, "part_0002")).read_source()
    assert second.units[0].ordinal == first.units[-1].ordinal + 1
    assert second.text == PART_TWO
    assert all(scene.id.startswith("p0002s") for scene in second.scenes)

    delta = read_extraction_delta(part_workspace(root, "part_0002"))
    assert set(delta.scene_ids) == {scene.id for scene in bible.scenes if scene.part_id == "part_0002"}
    assert [ref.entity_id for ref in delta.entities if ref.kind == "character"] == ["p0002s0001_char_001"]


def test_removed_names_stay_out_and_replacing_the_part_withdraws_it(tmp_path, monkeypatch) -> None:
    root = _series(tmp_path)
    config = Config(extraction_chunk_chars=4000)
    _fake_model(monkeypatch)
    before = _extract(root, "part_0001", config)
    edited = before.model_copy(deep=True)
    edited.excluded_entities = [ExcludedEntity(kind="character", name="ferryman")]
    artifacts.write_story_bible(root, edited)

    _fake_model(monkeypatch, newcomer="Ferryman")
    after = _extract(root, "part_0002", config)

    assert not any(character.name == "Ferryman" for character in after.characters)
    delta = read_extraction_delta(part_workspace(root, "part_0002"))
    assert "Ferryman" in delta.suppressed_names

    replace_part_text(root, "part_0002", PART_TWO + "One more line. ")
    withdrawn = artifacts.read_story_bible(root)
    assert {scene.part_id for scene in withdrawn.scenes} == {"part_0001"}
    assert {arc.part_id for arc in withdrawn.sequences} == {"part_0001"}
    assert load_state(part_workspace(root, "part_0002")).stages["extract"].status.value == "pending"


def test_a_later_part_waits_for_blank_anchors_before_any_model_call(tmp_path, monkeypatch) -> None:
    root = _series(tmp_path)
    config = Config(extraction_chunk_chars=4000)
    _fake_model(monkeypatch)
    earlier = _extract(root, "part_0001", config)
    # An extraction from before anchors were required can leave one blank.
    # Sections must keep known anchors verbatim, so no attempt could fix it.
    earlier.characters[0].visual_anchor = ""
    artifacts.write_story_bible(root, earlier)
    calls = _fake_model(monkeypatch, newcomer="Ferryman")

    workspace = part_workspace(root, "part_0002")
    with pytest.raises(MissingVisualAnchor, match=r"no visual anchor: Ari \(part0001_char_001\)"):
        s1_extract.estimate_cost(config, workspace, load_state(workspace))
    with pytest.raises(MissingVisualAnchor):
        _extract(root, "part_0002", config)
    assert calls == []


def _brief(**changes) -> AdaptationBrief:
    values = dict(
        status="approved", revision=2, story_promises=("A crossing",), themes=("passage",),
        point_of_view="close third on Ari", narrator_treatment="captions", tone="hushed",
        essential_events=("Ari crosses",), character_turns=("Ari commits to leaving",),
        desired_emphasis=("the gate",), motifs=("gates",), transformation_level="faithful",
        target_page_min=4, target_page_max=8,
    )
    values.update(changes)
    return AdaptationBrief(**values)


def test_a_later_part_brief_sees_only_its_part_and_inherits_direction(tmp_path, monkeypatch) -> None:
    root = _series(tmp_path)
    config = Config(extraction_chunk_chars=4000)
    _fake_model(monkeypatch)
    _extract(root, "part_0001", config)
    _fake_model(monkeypatch, newcomer="Ferryman")
    bible = _extract(root, "part_0002", config)
    source = TargetArtifacts(part_workspace(root, "part_0002")).read_source()

    prompt = build_brief_inference_prompt(source, bible, part_id="part_0002", previous_brief=_brief())
    context = json.loads(prompt[prompt.index("{"):])

    assert prompt.startswith("This source is one part of a longer series.")
    assert {scene["part_id"] for scene in context["story_bible"]["scenes"]} == {"part_0002"}
    assert context["series_direction"]["tone"] == "hushed"
    assert context["story_so_far"]["previous_part_scenes"]
    assert context["source_scenes"][0]["id"] == source.scenes[0].id
    assert "".join(scene["text"] for scene in context["source_scenes"]) == source.text

    inferred = _brief(status="draft", tone="raucous", themes=("noise",)).model_dump(
        exclude={"status", "revision", "content_sha256"})
    proposed = propose_brief(inferred, inherited={"tone": "hushed", "themes": ("passage",)})
    assert proposed.tone == "hushed"
    assert proposed.themes == ("passage",)
    assert proposed.status == "draft"


def test_every_part_of_a_multi_part_book_knows_its_place_in_brief_and_adapt(tmp_path, monkeypatch) -> None:
    from novel_to_comic.book_adaptation import build_narrative_treatment_prompt
    from novel_to_comic.continuity import continuity_context
    from novel_to_comic.models.story_bible import part_story_bible
    from novel_to_comic.stages.s2_brief import _inference_prompt

    root = _series(tmp_path)
    config = Config(extraction_chunk_chars=4000)
    _fake_model(monkeypatch)
    bible = _extract(root, "part_0001", config)
    first = part_workspace(root, "part_0001")

    prompt, _envelope, _inherited = _inference_prompt(first)
    context = json.loads(prompt[prompt.index("{"):])
    # Part 1 of 2 is not a complete story, even before any later part exists.
    assert prompt.startswith("This source is part 1 of 2 of one book.")
    assert "no ending of its own" in prompt
    assert "base themes and motifs on the book's" in prompt
    assert context["book_context"]["position"] == {"part": 1, "of": 2, "title": "Part 1"}
    assert context["book_context"]["map"]["this_part"]["role"] == "Stage 1 of the crossing"
    assert context["book_context"]["map"]["acts"][0]["last_part"] == "part_0002"

    continuity = continuity_context(first)
    assert set(continuity) == {"book_context"}
    treatment = build_narrative_treatment_prompt(
        TargetArtifacts(first).read_source(), part_story_bible(bible, "part_0001"), _brief(),
        continuity=continuity,
    )
    assert "Create one narrative treatment for this part's adaptation." in treatment
    assert "complete adaptation" not in treatment
    assert '"book_context"' in treatment and '"story_so_far"' not in treatment


def test_a_single_part_project_has_no_book_context(tmp_path) -> None:
    from novel_to_comic.book_context import book_context

    root = tmp_path / "book"
    root.mkdir()
    workspace = initialize_series(root, project_name="Crossing", novel_path=root / "novel.txt", text=PART_TWO)

    assert book_context(workspace) is None

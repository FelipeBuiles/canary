"""A later part extracts against the series Story Bible; its Brief inherits direction."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from novel_to_comic import artifacts
from novel_to_comic import extraction_sections as sections
from novel_to_comic.briefing import build_brief_inference_prompt, propose_brief
from novel_to_comic.config import Config
from novel_to_comic.models.adaptation import AdaptationBrief
from novel_to_comic.models.story_bible import ExcludedEntity
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
        "characters": characters, "locations": locations, "props": [], "narrative_arcs": [],
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
        if kwargs["feature"] == "extract.narrative_arcs":
            ids = [scene["id"] for scene in content["scenes"]]
            value = {"title": title, "author": "Unknown", "narrative_arcs": [
                {"act": act, "title": f"Act {act}", "scenes": ids if act == 1 else []} for act in (1, 2, 3)]}
        else:
            calls.append(content["id_prefix"])
            value = _section_payload(content, newcomer=newcomer)
        return ApiResult(value=value, usage=UsageRecord(provider="test", model="test", operation="text", cost_usd=0))

    monkeypatch.setattr(sections, "generate_json", generate)
    return calls


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


def test_a_later_part_continues_ids_ordinals_and_acts(tmp_path, monkeypatch) -> None:
    root = _series(tmp_path)
    # Part 1 is long enough to extract in sections; part 2 always uses them.
    config = Config(extraction_chunk_chars=4000)
    calls = _fake_model(monkeypatch, newcomer=None)
    _extract(root, "part_0001", config)
    calls_two = _fake_model(monkeypatch, newcomer="Ferryman", title="Ignored Retitle")
    bible = _extract(root, "part_0002", config)

    assert calls and all(prefix.startswith("part") for prefix in calls)
    assert calls_two and all(prefix.startswith("p0002s") for prefix in calls_two)
    assert bible.title == "Crossing"
    assert {scene.part_id for scene in bible.scenes} == {"part_0001", "part_0002"}
    ari = [character for character in bible.characters if character.id == "part0001_char_001"]
    assert len(ari) == 1 and ari[0].name == "Ari"
    assert any(character.name == "Ferryman" for character in bible.characters)
    assert {arc.part_id for arc in bible.narrative_arcs} == {"part_0001", "part_0002"}
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
    assert {arc.part_id for arc in withdrawn.narrative_arcs} == {"part_0001"}
    assert load_state(part_workspace(root, "part_0002")).stages["extract"].status.value == "pending"


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
    assert [unit["id"] for unit in context["source_units"]][0] == source.units[0].id

    inferred = _brief(status="draft", tone="raucous", themes=("noise",)).model_dump(
        exclude={"status", "revision", "content_sha256"})
    proposed = propose_brief(inferred, inherited={"tone": "hushed", "themes": ("passage",)})
    assert proposed.tone == "hushed"
    assert proposed.themes == ("passage",)
    assert proposed.status == "draft"

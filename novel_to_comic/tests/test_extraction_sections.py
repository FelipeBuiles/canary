"""Provider-free long-source recovery and continuity contracts."""

import json
import asyncio
from functools import wraps

import pytest

from novel_to_comic import artifacts
from novel_to_comic.config import Config
from novel_to_comic import extraction_sections as sections
from novel_to_comic.models.story_bible import StoryBible
from novel_to_comic.source_extraction import source_units, build_source_document, SourceSceneAnchor, align_scene_anchors
from novel_to_comic.stage_runtime import StageRuntime
from novel_to_comic.state import create_initial_state
from novel_to_comic.stages import s1_extract
from novel_to_comic.usage import ApiResult, UsageRecord


def run_async(fn):
    @wraps(fn)
    def run(*args, **kwargs):
        return asyncio.run(fn(*args, **kwargs))
    return run


def payload(index, text, state=None):
    prefix = f"part{index:04d}_"
    scene_id = prefix + "scene_001"
    character = {
        "id": "part0001_char_001", "name": "Ari", "visual_anchor": "adult, black hair",
        "age_range": "adult", "gender": "female", "distinguishing_features": [],
        "default_outfit": "coat", "first_appearance_scene": scene_id,
        "appearance_states": [], "appearance_timeline": [],
    }
    if state:
        character["appearance_states"] = [state]
        character["appearance_timeline"] = [{"state_id": state["id"], "at": {"scene_id": scene_id}}]
    return {
        "title": "Crossing", "author": "Unknown", "total_scenes": 1,
        "characters": [character],
        "locations": [{"id": "part0001_loc_001", "name": "Gate", "visual_anchor": "iron gate", "mood": "quiet"}],
        "scenes": [{"id": scene_id, "chapter": 1, "title": "Crossing", "location_id": "part0001_loc_001",
                    "character_ids": [character["id"]], "summary": "Ari crosses the gate.", "scene_type": "action",
                    "narrative_beat": "rising_action", "source_start_quote": source_units(text)[0].text.strip()}],
        "narrative_arcs": [], "props": [],
        "character_participation": [{"character_id": character["id"], "scene_id": scene_id,
                                     "classification": "direct_action", "source_quote": "Ari"}],
    }


def appearance(id="hurt"):
    return {"id": id, "label": id, "visual_anchor": "adult, black hair, bandaged arm",
            "changed_facets": ["damage"], "replaces_identity": False,
            "visually_significant": True, "continuity_guard": "Preserve the bandaged arm."}


def test_sentence_partition_preserves_all_original_offsets_and_unicode():
    text = ('Dr. Ari said, “Go!”\n\nThe gate opened at 3.5 seconds. A final thought…\n' * 100) + 'The end.'
    parts = sections.split_source(text, 4000)
    assert len(parts) > 1
    assert ''.join(parts) == text
    assert all(len(part) <= 4000 for part in parts)
    assert [u.text for part in parts for u in source_units(part)] == [u.text for u in source_units(text)]
    anchors = [SourceSceneAnchor(id=str(i), title=str(i), opening_quote=source_units(part)[0].text.strip())
               for i, part in enumerate(parts)]
    document = build_source_document(text, anchors)
    assert document.text == text
    assert document.scenes[-1].last_unit_id == document.units[-1].id


def test_oversized_sentence_fails_before_any_call():
    with pytest.raises(ValueError, match="sentence formatting"):
        sections.split_source("Ari " + "x" * 5000 + ".", 4000)


def test_merge_keeps_entity_scoped_states_and_cross_section_recovery():
    first = StoryBible.model_validate(payload(1, "Ari fell.", appearance()))
    second = StoryBible.model_validate(payload(2, "Ari recovered.", appearance("restored")))
    merged = sections.merge_section(first, second, "part0002_")
    assert len(merged.characters) == 1
    assert merged.characters[0].first_appearance_scene == "part0001_scene_001"
    assert [a.state_id for a in merged.characters[0].appearance_timeline] == ["hurt", "restored"]
    assert sections.registry_context(merged)["characters"][0]["carried_state_id"] == "restored"
    assert len(first.scenes) == 1  # failed/preview merges cannot mutate prior work


@pytest.mark.parametrize("change,match", [
    ("base", "base visual_anchor"), ("state", "state definition"),
    ("alias", "Reuse the registry ID"), ("location", "Unknown entity"),
    ("timeline", "only local timeline"), ("state_reference", "Unknown appearance"),
])
def test_merge_rejects_identity_drift_and_bad_references(change, match):
    first = StoryBible.model_validate(payload(1, "Ari fell.", appearance()))
    raw = payload(2, "Ari walked.", appearance())
    if change == "base":
        raw["characters"][0]["visual_anchor"] = "blonde"
    elif change == "state":
        raw["characters"][0]["appearance_states"][0]["continuity_guard"] = "Discard bandages."
    elif change == "alias":
        raw["characters"][0]["id"] = "part0002_char_001"
    elif change == "location":
        raw["scenes"][0]["location_id"] = "missing"
    elif change == "timeline":
        raw["characters"][0]["appearance_timeline"][0]["at"]["scene_id"] = "part0001_scene_001"
    elif change == "state_reference":
        raw["characters"][0]["appearance_timeline"][0]["state_id"] = "missing"
    with pytest.raises(ValueError, match=match):
        sections.merge_section(first, StoryBible.model_validate(raw), "part0002_")


@run_async
async def test_stage_timeout_resume_reuses_sections_and_publishes_complete_source(tmp_path, monkeypatch):
    text = "".join(f"Ari crossed gate number {i}. " for i in range(400))
    (tmp_path / "novel.txt").write_text(text)
    config = Config(extraction_chunk_chars=4000)
    calls = []
    should_fail = True

    async def generate(**kwargs):
        nonlocal should_fail
        content = json.loads(kwargs["user_content"])
        if kwargs["feature"] == "extract.narrative_arcs":
            ids = [s["id"] for s in content["scenes"]]
            value = {"title": "Crossing", "author": "Unknown", "narrative_arcs": [
                {"act": i, "title": f"Act {i}", "scenes": ids if i == 1 else []} for i in (1, 2, 3)]}
            calls.append("arcs")
        else:
            index = content["section"]
            calls.append(index)
            if index == 2 and should_fail:
                should_fail = False
                raise TimeoutError("runtime_timeout")
            value = payload(index, content["source_section"])
        return ApiResult(value=value, usage=UsageRecord(provider="test", model="test", operation="text", cost_usd=0))

    monkeypatch.setattr(sections, "generate_json", generate)
    state = create_initial_state("test", "novel.txt")
    ctx = StageRuntime("extract", state, tmp_path)
    with pytest.raises(TimeoutError):
        await s1_extract.run(config, tmp_path, ctx)
    assert calls == [1, 2]  # no automatic timeout resubmission
    assert not artifacts.story_bible_path(tmp_path).exists()
    assert len(list((tmp_path / ".checkpoints/extract/responses").glob("*.json"))) == 1
    result = await s1_extract.run(config, tmp_path, ctx)
    assert calls.count(1) == 1
    assert calls.count(2) == 2
    assert result.total_scenes == len(sections.split_source(text, 4000))
    assert state.stages["extract"].items_done == state.stages["extract"].items_total
    assert json.loads((tmp_path / "source/source.json").read_text())["text"] == text
    before = list(calls)
    await s1_extract.run(config, tmp_path, ctx)
    assert calls == before  # including final organization


@run_async
async def test_section_validation_repair_is_scoped_and_cached(tmp_path, monkeypatch):
    text = "Ari crossed the gate. " * 400
    count = 0
    async def generate(**kwargs):
        nonlocal count
        count += 1
        content = kwargs["user_content"]
        if kwargs["feature"] == "extract.narrative_arcs":
            ids = [s["id"] for s in json.loads(content)["scenes"]]
            return ApiResult(value={"title": "Crossing", "author": "Unknown", "narrative_arcs": [
                {"act": i, "title": str(i), "scenes": ids if i == 1 else []} for i in (1, 2, 3)]})
        if content.startswith("Your previous"):
            # The repair contains only this section and its established registry.
            assert len(content) < len(text) + len(json.dumps(payload(2, text))) + 5000
            return ApiResult(value=payload(2, text))
        data = json.loads(content)
        value = payload(data["section"], data["source_section"])
        if data["section"] == 2:
            value["characters"][0]["visual_anchor"] = "incorrect new identity"
        return ApiResult(value=value)
    monkeypatch.setattr(sections, "generate_json", generate)
    config = Config(extraction_chunk_chars=4000)
    ctx = StageRuntime("extract", create_initial_state("test", "novel.txt"), tmp_path)
    ctx.begin()
    bible = await sections.extract_sections(config, tmp_path, ctx, text, s1_extract.PROMPT_PATH.read_text())
    assert bible.characters[0].visual_anchor == "adult, black hair"
    # Identical sentences in earlier sections must not steal later boundaries.
    offsets = [0]
    for part in sections.split_source(text, 4000)[:-1]:
        offsets.append(offsets[-1] + len(part))
    assert [scene.source_start_offset for scene in bible.scenes] == offsets
    assert align_scene_anchors(bible, text) == ()
    document = build_source_document(text, [
        SourceSceneAnchor(id=s.id, title=s.title, opening_quote=s.source_start_quote,
                          start_offset=s.source_start_offset) for s in bible.scenes
    ])
    unit_starts = {u.id: u.start_offset for u in document.units}
    assert [unit_starts[s.first_unit_id] for s in document.scenes] == offsets
    assert count == len(sections.split_source(text, 4000)) + 2
    before = count
    await sections.extract_sections(config, tmp_path, ctx, text, s1_extract.PROMPT_PATH.read_text())
    assert count == before


def test_explicit_invalid_offset_never_falls_back_to_a_different_occurrence():
    text = "Ari left. Ari left."
    bible = StoryBible.model_validate(payload(1, text))
    bible.scenes[0].source_start_offset = 1
    assert align_scene_anchors(bible, text) == (bible.scenes[0].id,)
    with pytest.raises(ValueError):
        build_source_document(text, [SourceSceneAnchor(
            id="bad", title="bad", opening_quote="Ari left.", start_offset=1)])


def test_existing_entity_delta_inherits_authorities_without_repeating_old_transitions():
    previous = StoryBible.model_validate(payload(1, 'Ari fell.', appearance()))
    raw = payload(2, 'Ari recovered.')
    raw['characters'] = [{'id': 'part0001_char_001', 'appearance_timeline': [
        {'state_id': 'hurt', 'at': {'scene_id': 'part0002_scene_001'}}]}]
    raw['locations'] = [{'id': 'part0001_loc_001'}]
    hydrated = sections.hydrate_section(raw, previous)
    parsed = s1_extract._parse_extraction(hydrated, 'Ari recovered.')
    merged = sections.merge_section(previous, parsed, 'part0002_')
    character = merged.characters[0]
    assert character.visual_anchor == previous.characters[0].visual_anchor
    assert character.appearance_states == previous.characters[0].appearance_states
    assert [item.at.scene_id for item in character.appearance_timeline] == [
        'part0001_scene_001', 'part0002_scene_001']
    assert 'visual_anchor' not in raw['characters'][0]
    assert len(json.dumps(raw)) < len(json.dumps(hydrated))


def test_entity_delta_does_not_hide_explicit_identity_or_state_conflicts():
    previous = StoryBible.model_validate(payload(1, 'Ari fell.', appearance()))
    raw = payload(2, 'Ari walked.')
    raw['characters'] = [{'id': 'part0001_char_001', 'visual_anchor': 'different identity'}]
    hydrated = sections.hydrate_section(raw, previous)
    parsed = s1_extract._parse_extraction(hydrated, 'Ari walked.')
    with pytest.raises(ValueError, match='base visual_anchor'):
        sections.merge_section(previous, parsed, 'part0002_')


def test_section_inherits_book_metadata_and_ignores_only_unused_known_id_echoes():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    previous.characters.append(previous.characters[0].model_copy(update={
        'id': 'part0001_char_002', 'name': 'Keeper'}))
    raw = payload(2, 'Ari closed the gate.')
    raw.pop('title')
    raw.pop('author')
    raw.pop('total_scenes')
    raw['characters'].append({'id': 'part0001_char_002'})
    hydrated = sections.hydrate_section(raw, previous)
    assert hydrated['title'] == previous.title
    assert hydrated['author'] == previous.author
    assert [c['id'] for c in hydrated['characters']] == ['part0001_char_001']
    parsed = s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')
    merged = sections.merge_section(previous, parsed, 'part0002_')
    assert len(merged.characters) == 2  # the book still retains the earlier keeper
    raw['characters'][-1]['appearance_timeline'] = []
    assert len(sections.hydrate_section(raw, previous)['characters']) == 2
    raw['characters'][-1] = {'id': 'part0002_char_unknown'}
    assert len(sections.hydrate_section(raw, previous)['characters']) == 2


@run_async
async def test_section_repairs_metadata_and_evidence_locally_without_model_retry():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    for key in ('title', 'author', 'total_scenes'):
        raw.pop(key)
    raw['characters'][0].update(default_outfit=None, gender=None)
    raw['character_participation'] = []
    calls = []
    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value=raw)
    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', 'Ari closed the gate.', generate=generate,
        prepare=lambda value: sections.hydrate_section(value, previous),
        validate=lambda value: sections.merge_section(previous, value, 'part0002_'))
    assert len(calls) == 1
    assert result.value.scenes[0].character_ids == ['part0001_char_001']
    assert result.value.total_scenes == 1


@pytest.mark.parametrize('reference', ['roster', 'evidence', 'both', 'background'])
def test_section_resolves_omitted_known_entities_from_references(reference):
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.', appearance()))
    raw = payload(2, 'Ari closed the gate.')
    raw.pop('characters')
    raw.pop('locations')
    if reference == 'roster':
        raw['character_participation'] = []
    elif reference == 'evidence':
        raw['scenes'][0]['character_ids'] = []
    elif reference == 'background':
        raw['scenes'][0]['character_ids'] = []
        raw['character_participation'][0]['classification'] = 'background_only'
    hydrated = sections.hydrate_section(raw, previous)
    assert hydrated['characters'][0]['visual_anchor'] == previous.characters[0].visual_anchor
    assert hydrated['characters'][0]['appearance_states'] == previous.characters[0].model_dump(mode='json')['appearance_states']
    assert hydrated['characters'][0]['appearance_timeline'] == []
    assert hydrated['locations'][0]['id'] == 'part0001_loc_001'
    assert 'characters' not in raw
    parsed = s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')
    merged = sections.merge_section(previous, parsed, 'part0002_')
    assert merged.characters == previous.characters
    assert parsed.scenes[0].character_ids == ([] if reference == 'background' else ['part0001_char_001'])
    assert len(merged.scenes) == 2


@pytest.mark.parametrize('unknown', ['character', 'scene', 'both'])
def test_registry_resolution_never_invents_unknown_entities_or_imports_old_scenes(unknown):
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    raw['characters'] = []
    evidence = raw['character_participation'][0]
    if unknown in {'character', 'both'}:
        evidence['character_id'] = 'part0002_unknown'
        raw['scenes'][0]['character_ids'] = ['part0002_unknown']
    if unknown in {'scene', 'both'}:
        evidence['scene_id'] = 'part0001_scene_001'
    hydrated = sections.hydrate_section(raw, previous)
    with pytest.raises(ValueError, match='Participation evidence must reference') as error:
        s1_extract._parse_extraction(hydrated, 'Ari closed the gate.')
    if unknown in {'character', 'both'}:
        assert 'part0002_unknown' in str(error.value)
        assert not hydrated['characters']
    if unknown in {'scene', 'both'}:
        assert 'part0001_scene_001' in str(error.value)
        assert len(hydrated['scenes']) == 1


@run_async
async def test_omitted_known_definitions_need_one_response_not_a_correction():
    previous = StoryBible.model_validate(payload(1, 'Ari opened the gate.'))
    raw = payload(2, 'Ari closed the gate.')
    raw['characters'] = []
    raw['locations'] = []
    calls = 0
    async def generate(**kwargs):
        nonlocal calls
        calls += 1
        assert calls == 1, 'Registry assembly must not need a model correction'
        return ApiResult(value=raw)
    result = await s1_extract._extract_with_retry(
        Config(), 'instructions', 'Ari closed the gate.', generate=generate,
        prepare=lambda value: sections.hydrate_section(value, previous),
        validate=lambda value: sections.merge_section(previous, value, 'part0002_'))
    assert result.value.characters[0].id == 'part0001_char_001'
    assert calls == 1

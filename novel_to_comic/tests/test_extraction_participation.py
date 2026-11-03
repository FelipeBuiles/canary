"""Extraction-only participation evidence protects the canonical visual roster."""

import asyncio

import pytest

from novel_to_comic.config import Config
from novel_to_comic.stages.s1_extract import (
    _ParticipationQuoteMismatch,
    _UnresolvedSceneOpenings,
    _UnclassifiedCharacters,
    _extract_with_retry,
    _parse_extraction,
    _participation_quote_correction,
)
from novel_to_comic.usage import ApiResult


SOURCE = (
    "Ari opened the gate. A photograph of Jo stood on the shelf. "
    "Ari remembered: Ren pulled the injured sailor aboard and wrapped him in a blanket. "
    "The keeper raised a lantern and explained the crossing."
)


def _payload():
    characters = [
        {
            "id": name, "name": name, "visual_anchor": "1man, adult male",
            "age_range": "adult", "gender": "male", "distinguishing_features": [],
            "default_outfit": "", "relationships": [], "first_appearance_scene": "now",
        }
        for name in ("Ari", "Jo", "Ren", "keeper")
    ]
    characters[0]["relationships"] = [{"character_id": "Jo", "relationship": "friend"}]
    scenes = [
        {"id": scene_id, "chapter": 1, "title": scene_id, "location_id": "gate",
         "character_ids": ids, "summary": summary, "scene_type": "action",
         "narrative_beat": "rising_action", "source_start_quote": quote}
        for scene_id, ids, summary, quote in (
            ("now", ["Ari", "Jo", "Ren"], "Ari opens the gate and remembers Ren; Jo is in a photo.", "Ari opened the gate."),
            ("memory", ["Ren"], "Ren rescues the sailor.", "Ari remembered:"),
            ("crossing", ["keeper"], "The keeper explains the crossing.", "The keeper raised a lantern and explained the crossing."),
        )
    ]
    return {
        "title": "Crossing", "author": "Unknown", "total_scenes": 3,
        "characters": characters, "locations": [], "scenes": scenes,
        "sequences": [], "props": [],
        "character_participation": [
            {"character_id": character_id, "scene_id": scene_id,
             "classification": classification, "source_quote": quote}
            for character_id, scene_id, classification, quote in (
                ("Ari", "now", "direct_action", "Ari opened the gate."),
                ("Jo", "now", "background_only", "A photograph of Jo stood on the shelf."),
                ("Ren", "now", "background_only", "Ari remembered:"),
                ("Ren", "memory", "staged_recollection", "Ren pulled the injured sailor aboard and wrapped him in a blanket."),
                ("keeper", "crossing", "direct_action", "The keeper raised a lantern and explained the crossing."),
            )
        ],
    }


def test_extraction_excludes_background_but_retains_embodied_memory_and_one_scene_actor():
    bible = _parse_extraction(_payload(), SOURCE)
    assert [character.id for character in bible.characters] == ["Ari", "Ren", "keeper"]
    assert [scene.character_ids for scene in bible.scenes] == [["Ari"], ["Ren"], ["keeper"]]
    assert bible.characters[0].relationships == []
    assert bible.characters[1].first_appearance_scene == "memory"
    assert "Jo is in a photo" in bible.scenes[0].summary
    assert "character_participation" not in bible.model_dump()


def test_extraction_accepts_whitespace_differences_without_rewriting_evidence():
    payload = _payload()
    quote = " \tAri  opened\n the gate.\r\n"
    payload["character_participation"][0]["source_quote"] = quote
    wrapped_source = SOURCE.replace(" ", "\n\t")

    bible = _parse_extraction(payload, wrapped_source)

    assert [character.id for character in bible.characters] == ["Ari", "Ren", "keeper"]
    assert [scene.character_ids for scene in bible.scenes] == [["Ari"], ["Ren"], ["keeper"]]
    assert payload["character_participation"][0]["source_quote"] == quote
    assert payload["character_participation"][3]["source_quote"] == (
        "Ren pulled the injured sailor aboard and wrapped him in a blanket."
    )


@pytest.mark.parametrize("quote", [" \t\r\n ", ""])
def test_extraction_rejects_empty_participation_evidence(quote):
    payload = _payload()
    payload["character_participation"][0]["source_quote"] = quote

    with pytest.raises(ValueError):
        _parse_extraction(payload, SOURCE.replace(" ", "\n\t"))


@pytest.mark.parametrize("quote", [
    "Ari closed the gate.",
    "Ari opened the gate!",
    "ari opened the gate.",
])
def test_extraction_recovers_nonempty_paraphrased_evidence_from_its_scene_anchor(quote):
    payload = _payload()
    payload["character_participation"][0]["source_quote"] = quote

    bible = _parse_extraction(payload, SOURCE)

    assert [character.id for character in bible.characters] == ["Ari", "Ren", "keeper"]


def test_extraction_adds_a_staged_participant_omitted_from_the_scene_roster():
    payload = _payload()
    payload["character_participation"].append({
        "character_id": "Ari",
        "scene_id": "memory",
        "classification": "staged_recollection",
        "source_quote": "Ren pulled the injured sailor aboard and wrapped him in a blanket.",
    })

    bible = _parse_extraction(payload, SOURCE)

    memory = next(scene for scene in bible.scenes if scene.id == "memory")
    assert memory.character_ids == ["Ren", "Ari"]


def test_extraction_recovers_missing_evidence_for_a_rostered_participant():
    payload = _payload()
    payload["character_participation"].pop(0)

    bible = _parse_extraction(payload, SOURCE)

    now = next(scene for scene in bible.scenes if scene.id == "now")
    assert now.character_ids == ["Ari"]


def test_unclassified_candidates_are_named_for_one_targeted_correction():
    payload = _payload()
    for cid, name in [("residents", "Elderly residents"), ("stranger", "Unseen stranger")]:
        payload["characters"].append({**payload["characters"][0], "id": cid, "name": name})

    with pytest.raises(_UnclassifiedCharacters) as error:
        _parse_extraction(payload, SOURCE)

    assert error.value.characters == (
        ("residents", "Elderly residents", "now"), ("stranger", "Unseen stranger", "now"),
    )
    assert "residents ('Elderly residents')" in str(error.value)
    assert "stranger ('Unseen stranger')" in str(error.value)
    correction = _participation_quote_correction(error.value)
    assert "character_id='residents', name='Elderly residents', first_appearance_scene='now'" in correction
    assert "direct_action or staged_recollection" in correction
    assert "remove its Character entry" in correction
    assert "Never invent" in correction
    assert "entire corrected Story Bible JSON object" in correction
    # The rejected payload stays intact for the model; no classification or
    # visual membership was inferred from a character definition alone.
    assert len(payload["characters"]) == 6
    assert all("residents" not in scene["character_ids"] for scene in payload["scenes"])


def test_ungrounded_evidence_reports_its_unresolved_scene_opening():
    payload = _payload()
    payload["scenes"][0]["source_start_quote"] = "Not a source sentence."
    payload["character_participation"][1]["source_quote"] = "Jo walked into the room."
    with pytest.raises(_UnresolvedSceneOpenings, match="Unresolved scene IDs: now$") as error:
        _parse_extraction(payload, SOURCE)
    assert error.value.openings == (("now", "Not a source sentence.", None),)
    correction = _participation_quote_correction(error.value)
    assert "scene_id='now', source_start_quote='Not a source sentence.'" in correction
    assert "never the registry or earlier text" in correction
    assert "entire corrected Story Bible JSON object" in correction
    payload = _payload()
    payload["scenes"][0]["source_start_quote"] = "Not a source sentence."
    payload["character_participation"].pop(0)
    with pytest.raises(_UnresolvedSceneOpenings, match="now"):
        _parse_extraction(payload, SOURCE)


def test_ungrounded_evidence_in_an_invalid_scene_still_reports_the_quote():
    payload = _payload()
    payload["scenes"][0]["source_start_quote"] = None
    payload["character_participation"][1]["source_quote"] = "Jo walked into the room."
    with pytest.raises(_ParticipationQuoteMismatch, match="verbatim") as error:
        _parse_extraction(payload, SOURCE)
    assert error.value.pair == ("Jo", "now")
    correction = _participation_quote_correction(error.value)
    assert "source_quote='Jo walked into the room.'" in correction
    assert "Do not reconstruct, normalize, or paraphrase it." in correction
    assert "never return a character_participation entry or field by itself" in correction


def test_extraction_reports_all_unresolved_openings_for_one_repair():
    payload = _payload()
    payload["scenes"][0]["source_start_quote"] = "Not a source sentence."
    payload["scenes"][1]["source_start_quote"] = "Another missing source sentence."
    payload["character_participation"][0]["source_quote"] = "Ari opened the gate!"
    payload["character_participation"][3]["source_quote"] = "Ren abandoned the sailor."

    with pytest.raises(_UnresolvedSceneOpenings) as error:
        _parse_extraction(payload, SOURCE)

    assert error.value.openings == (
        ("now", "Not a source sentence.", None),
        ("memory", "Another missing source sentence.", None),
    )
    correction = _participation_quote_correction(error.value)
    assert "source_start_quote='Not a source sentence.'" in correction
    assert "source_start_quote='Another missing source sentence.'" in correction


def test_ungrounded_evidence_in_a_repeated_opening_reports_the_order_fault():
    payload = _payload()
    payload["scenes"][1]["source_start_quote"] = "Ari opened the gate."
    payload["character_participation"][3]["source_quote"] = "Ren rescued the sailor."
    with pytest.raises(_UnresolvedSceneOpenings) as error:
        _parse_extraction(payload, SOURCE)
    assert error.value.openings == (("memory", "Ari opened the gate.", None),)
    assert error.value.out_of_order == {"memory": "now"}
    assert "opens_before_previous_scene='now'" in _participation_quote_correction(error.value)


def test_repeated_opening_retry_names_the_order_fault_and_recovers():
    initial, corrected = _payload(), _payload()
    for payload in (initial, corrected):
        payload["locations"] = [{"id": "gate", "name": "Gate", "visual_anchor": "iron gate", "mood": "quiet"}]
    initial["scenes"][1]["source_start_quote"] = "Ari opened the gate."
    calls = []

    async def generate(**kwargs):
        calls.append(kwargs)
        return ApiResult(value=[initial, corrected][len(calls) - 1])

    result = asyncio.run(_extract_with_retry(Config(), "instructions", SOURCE, generate=generate))
    assert [scene.id for scene in result.value.scenes] == ["now", "memory", "crossing"]
    assert len(calls) == 2
    assert "opens_before_previous_scene='now'" in calls[1]["user_content"]


def test_background_evidence_for_an_undefined_character_is_dropped_locally():
    payload = _payload()
    payload["character_participation"].append({
        "character_id": "stranger", "scene_id": "now",
        "classification": "background_only", "source_quote": "A photograph of Jo stood on the shelf.",
    })
    bible = _parse_extraction(payload, SOURCE)
    assert "stranger" not in {character.id for character in bible.characters}
    payload["character_participation"][-1]["classification"] = "direct_action"
    with pytest.raises(ValueError, match="Undefined character IDs: \\['stranger'\\]"):
        _parse_extraction(payload, SOURCE)


def test_undefined_background_character_relationships_are_removed_with_its_evidence():
    payload = _payload()
    payload["characters"] = [character for character in payload["characters"] if character["id"] != "Jo"]
    payload["scenes"][0]["character_ids"].remove("Jo")
    payload["characters"][1]["relationships"] = [{"character_id": "Jo", "relationship": "friend"}]

    bible = _parse_extraction(payload, SOURCE)

    assert [character.id for character in bible.characters] == ["Ari", "Ren", "keeper"]
    assert all(not character.relationships for character in bible.characters)
    assert [scene.character_ids for scene in bible.scenes] == [["Ari"], ["Ren"], ["keeper"]]
    assert "Jo is in a photo" in bible.scenes[0].summary
    # Keep the provider response intact for checkpoint replay and correction.
    assert payload["characters"][0]["relationships"][0]["character_id"] == "Jo"
    assert any(evidence["character_id"] == "Jo" for evidence in payload["character_participation"])


def test_background_evidence_never_hides_undefined_staged_participation():
    payload = _payload()
    payload["characters"] = [character for character in payload["characters"] if character["id"] != "Jo"]
    payload["scenes"][0]["character_ids"].remove("Jo")
    payload["character_participation"].append({
        "character_id": "Jo", "scene_id": "memory",
        "classification": "staged_recollection", "source_quote": "Ren pulled the injured sailor aboard",
    })

    with pytest.raises(ValueError, match="Undefined character IDs: \\['Jo'\\]"):
        _parse_extraction(payload, SOURCE)


def test_extraction_preserves_nonhuman_anchor_verbatim_despite_adult_gender_metadata():
    payload = _payload()
    anchor = "1cat,  tortoiseshell persian cat, flat face, fluffy fur"
    payload["characters"][0].update(visual_anchor=anchor, gender="nonbinary", age_range="adult")
    bible = _parse_extraction(payload, SOURCE)
    assert bible.characters[0].visual_anchor == anchor


def test_extraction_rejects_collapsed_illness_and_recovery_interval():
    payload = _payload()
    char = payload["characters"][0]
    char["appearance_states"] = [
        {"id": state, "label": state, "visual_anchor": char["visual_anchor"],
         "changed_facets": [], "replaces_identity": False}
        for state in ("ill", "recovered")
    ]
    char["appearance_timeline"] = [
        {"state_id": state, "at": {"scene_id": "now", "beat": None}}
        for state in ("ill", "recovered")
    ]
    with pytest.raises(ValueError, match="Conflicting appearance activations"):
        _parse_extraction(payload, SOURCE)
    char["appearance_timeline"][1]["at"]["beat"] = 2
    assert len(_parse_extraction(payload, SOURCE).characters[0].appearance_timeline) == 2


def test_extraction_requires_explicit_state_conditioning_facets():
    payload = _payload()
    payload["characters"][0]["appearance_states"] = [
        {"id": "white_hair", "label": "White hair", "visual_anchor": "adult male, white hair"},
    ]
    with pytest.raises(ValueError, match="must explicitly declare changed_facets"):
        _parse_extraction(payload, SOURCE)
    payload["characters"][0]["appearance_states"][0].update(changed_facets=["hair"], replaces_identity=False)
    assert _parse_extraction(payload, SOURCE).characters[0].appearance_states[0].changed_facets == ("hair",)


def test_scene_evidence_resolution_does_not_depend_on_book_or_character_metadata():
    from novel_to_comic.stages.s1_extract import _resolved_scene_anchor_quotes

    payload = _payload()
    payload.pop('title')
    payload.pop('author')
    payload.pop('total_scenes')
    payload['characters'][0]['gender'] = None
    payload['characters'][0]['default_outfit'] = None
    quotes, unresolved = _resolved_scene_anchor_quotes(payload, SOURCE)
    assert not unresolved
    assert set(quotes) == {'now', 'memory', 'crossing'}
    assert quotes['crossing'] == 'The keeper raised a lantern and explained the crossing.'
    # One malformed opening must not suppress unrelated resolved scenes either.
    payload['scenes'][1]['source_start_quote'] = None
    assert set(_resolved_scene_anchor_quotes(payload, SOURCE)[0]) == {'now', 'crossing'}


@pytest.mark.parametrize('scene_count', [None, 99])
def test_extract_derives_scene_count_and_preserves_explicitly_unknown_descriptions(scene_count):
    payload = _payload()
    if scene_count is None:
        payload.pop('total_scenes')
    else:
        payload['total_scenes'] = scene_count
    payload['characters'][0].update(gender=None, age_range=None, default_outfit=None)
    payload['character_participation'].pop(0)  # recover the roster entry from its source opening
    bible = _parse_extraction(payload, SOURCE)
    assert bible.total_scenes == len(bible.scenes) == 3
    assert bible.characters[0].gender == bible.characters[0].age_range == bible.characters[0].default_outfit == ''
    assert bible.characters[0].visual_anchor == '1man, adult male'
    assert payload['characters'][0]['default_outfit'] is None


@pytest.mark.parametrize('reverse', [False, True])
def test_multiple_passages_consolidate_staged_participation_without_promoting_background(reverse):
    payload = _payload()
    original = payload['character_participation'][0]
    payload['character_participation'].extend([
        {**original, 'source_quote': 'opened the gate'},
        {**original, 'classification': 'background_only', 'source_quote': 'A photograph'},
        dict(payload['character_participation'][1]),  # Jo is still background only
    ])
    if reverse:
        payload['character_participation'].reverse()
    bible = _parse_extraction(payload, SOURCE)
    assert bible.scenes[0].character_ids == ['Ari']
    assert 'Jo' not in {c.id for c in bible.characters}


def test_duplicate_participation_does_not_skip_evidence_validation():
    payload = _payload()
    payload['scenes'][0]['source_start_quote'] = 'No matching source opening.'
    payload['character_participation'].append({
        **payload['character_participation'][0], 'source_quote': 'An invented event.'})
    with pytest.raises(_UnresolvedSceneOpenings):
        _parse_extraction(payload, SOURCE)


def test_missing_descriptive_field_still_reports_real_schema_error():
    payload = _payload()
    payload['characters'][0].pop('default_outfit')
    payload['character_participation'].pop(0)
    with pytest.raises(ValueError, match='default_outfit') as error:
        _parse_extraction(payload, SOURCE)
    assert 'Missing participation evidence' not in str(error.value)


def test_unresolved_missing_evidence_is_reported_together_for_one_correction():
    payload = _payload()
    payload['scenes'][0]['source_start_quote'] = 'Missing first opening.'
    payload['scenes'][2]['source_start_quote'] = 'Missing last opening.'
    payload['character_participation'] = [row for row in payload['character_participation']
                                          if row['character_id'] not in {'Ari', 'keeper'}]
    with pytest.raises(_UnresolvedSceneOpenings) as error:
        _parse_extraction(payload, SOURCE)
    assert [scene_id for scene_id, _, _ in error.value.openings] == ['now', 'crossing']


def _state(state_id, anchor, **extra):
    return {"id": state_id, "label": state_id, "visual_anchor": anchor, "visually_significant": True,
            "changed_facets": ["clothing"], "replaces_identity": False, **extra}


@pytest.mark.parametrize("name", ["The Two Police Officers", "Pair of Guards", "The Palace Guards", "the twins"])
def test_extraction_rejects_a_group_merged_into_one_character(name):
    payload = _payload()
    payload["characters"][3]["name"] = name
    with pytest.raises(ValueError, match="names a group"):
        _parse_extraction(payload, SOURCE)


def test_extraction_keeps_singular_role_names():
    payload = _payload()
    payload["characters"][3]["name"] = "Captain of the Guards"
    assert _parse_extraction(payload, SOURCE).characters[2].name == "Captain of the Guards"


def test_extraction_rejects_explicit_anatomy_tags():
    payload = _payload()
    payload["characters"][0]["appearance_states"] = [
        _state("dressed", "1man, adult male, bare skin with no belly button or genitals, old t-shirt"),
    ]
    with pytest.raises(ValueError, match="Ari/dressed tags genitals"):
        _parse_extraction(payload, SOURCE)


def test_extraction_rejects_duplicate_looks_but_allows_a_canonical_return():
    payload = _payload()
    payload["characters"][0]["visual_anchor"] = "1man, adult male, white spacesuit, helmet"
    payload["characters"][0]["appearance_states"] = [
        _state("suit_off", "1man, adult male, grey t-shirt"),
        _state("suit_again", "1man, adult male, helmet, white spacesuit"),
    ]
    with pytest.raises(ValueError, match="Ari/suit_again declares a physical change but repeats the base"):
        _parse_extraction(payload, SOURCE)

    payload["characters"][0]["appearance_states"][1]["canonical_equivalent"] = True
    assert len(_parse_extraction(payload, SOURCE).characters[0].appearance_states) == 2


@pytest.mark.parametrize("anchor", ["", "  "])
def test_extraction_rejects_a_blank_visual_anchor_for_correction(anchor):
    payload = _payload()
    payload["characters"][0]["visual_anchor"] = anchor
    with pytest.raises(ValueError, match=r"Blank visual_anchor for: Ari \(Ari\)"):
        _parse_extraction(payload, SOURCE)

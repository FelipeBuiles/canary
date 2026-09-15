"""Extraction-only participation evidence protects the canonical visual roster."""

import pytest

from novel_to_comic.stages.s1_extract import (
    _ParticipationQuoteMismatch,
    _parse_extraction,
    _participation_quote_correction,
)


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
        "narrative_arcs": [], "props": [],
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


def test_extraction_rejects_ungrounded_or_missing_participation():
    payload = _payload()
    payload["scenes"][0]["source_start_quote"] = "Not a source sentence."
    payload["character_participation"][1]["source_quote"] = "Jo walked into the room."
    with pytest.raises(_ParticipationQuoteMismatch, match="verbatim") as error:
        _parse_extraction(payload, SOURCE)
    assert error.value.pair == ("Jo", "now")
    assert error.value.source_quote == "Jo walked into the room."
    correction = _participation_quote_correction(error.value)
    assert "character_id='Jo'" in correction
    assert "scene_id='now'" in correction
    assert "source_quote='Jo walked into the room.'" in correction
    assert "Do not reconstruct, normalize, or paraphrase it." in correction
    assert "entire corrected Story Bible JSON object" in correction
    assert "never return a character_participation entry or field by itself" in correction
    payload = _payload()
    payload["scenes"][0]["source_start_quote"] = "Not a source sentence."
    payload["character_participation"].pop(1)
    with pytest.raises(ValueError, match="Missing participation evidence"):
        _parse_extraction(payload, SOURCE)


def test_extraction_reports_all_invalid_participation_quotes_for_one_repair():
    payload = _payload()
    payload["scenes"][0]["source_start_quote"] = "Not a source sentence."
    payload["scenes"][1]["source_start_quote"] = "Another missing source sentence."
    payload["character_participation"][0]["source_quote"] = "Ari opened the gate!"
    payload["character_participation"][3]["source_quote"] = "Ren abandoned the sailor."

    with pytest.raises(_ParticipationQuoteMismatch) as error:
        _parse_extraction(payload, SOURCE)

    assert [(pair, quote) for pair, quote, _ in error.value.mismatches] == [
        (("Ari", "now"), "Ari opened the gate!"),
        (("Ren", "memory"), "Ren abandoned the sailor."),
    ]
    assert error.value.mismatches[0][2] == "Ari opened the gate."
    assert error.value.mismatches[1][2] is None
    correction = _participation_quote_correction(error.value)
    assert "source_quote='Ari opened the gate!'" in correction
    assert "source_quote='Ren abandoned the sailor.'" in correction
    assert "exact_source_replacement='Ari opened the gate.'" in correction


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

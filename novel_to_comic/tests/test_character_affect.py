from pathlib import Path

from novel_to_comic.models.appearance import AppearanceState
from novel_to_comic.models.story_bible import Character


def test_character_and_state_affect_are_separate_from_visual_identity():
    state = AppearanceState(
        id="delirious",
        label="Delirious",
        visual_anchor="1man, hospital gown, sweating",
        baseline_affect="feverish and disoriented",
    )
    character = Character(
        id="char_001",
        name="Henry",
        visual_anchor="1man, pale skin, messy dark hair, artist smock",
        age_range="early 20s",
        gender="male",
        distinguishing_features=["messy dark hair"],
        baseline_affect="quietly uneasy",
        default_outfit="paint-stained artist smock",
        first_appearance_scene="scene_001",
        appearance_states=[state],
    )

    assert "uneasy" not in character.visual_anchor
    assert character.baseline_affect == "quietly uneasy"
    assert character.appearance_states[0].baseline_affect == "feverish and disoriented"


def test_extraction_contract_excludes_affect_from_visual_anchor():
    prompt_path = (
        Path(__file__).parents[1]
        / "src"
        / "novel_to_comic"
        / "prompts"
        / "extraction.txt"
    )
    prompt = prompt_path.read_text()

    assert '"baseline_affect"' in prompt
    assert "NO emotion, expression, mood, pose, action" in prompt
    assert "It is NOT part of visual_anchor" in prompt


def test_extraction_contract_keeps_source_order_and_important_speakers():
    prompt_path = (
        Path(__file__).parents[1]
        / "src"
        / "novel_to_comic"
        / "prompts"
        / "extraction.txt"
    )
    prompt = prompt_path.read_text()

    assert "strict source-text order" in prompt
    assert "monotonically later" in prompt
    assert "named on-screen speaking character" in prompt
    assert "only one scene" in prompt


def test_extraction_contract_requires_first_response_appearance_transitions():
    prompt_path = (
        Path(__file__).parents[1]
        / "src"
        / "novel_to_comic"
        / "prompts"
        / "extraction.txt"
    )
    prompt = prompt_path.read_text()

    assert "VISIBLE-CHANGE INVENTORY" in prompt
    assert "temporary or reversible" in prompt
    assert "fever, delirium, unconsciousness, recovery" in prompt
    assert "hair turns white from shock" in prompt
    assert "reported, remembered, or presented through a diary" in prompt
    assert "Do not put the later look in the base visual_anchor" in prompt
    assert '"canonical_equivalent": true' in prompt
    assert "explicit before/after change" in prompt

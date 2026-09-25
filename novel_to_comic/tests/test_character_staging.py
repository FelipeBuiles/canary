"""Per-panel acting direction and neutral turnaround references.

A single three-quarter reference with a baked-in mood made every panel repeat
the same view and face. Identity now comes from a neutral turnaround sheet;
facing, gaze, expression and camera come from Plan, per panel.
"""
from types import SimpleNamespace

import pytest
from PIL import Image
from pydantic import ValidationError

from novel_to_comic.generation_input import GenerationPromptInput, PromptSubject
from novel_to_comic.generation_prompt import generate_system_constraints
from novel_to_comic.models.page import (
    ApprovedVisualReference,
    ApprovedVisualReferenceInventory,
    CharacterActing,
    PageContent,
    PanelCamera,
)
from novel_to_comic.page_drawing import compile_page_generation_request
from novel_to_comic.page_planning import _staging_failures
from novel_to_comic.stages.s3_cast import _crop_sheet_to_poses

from tests.test_complete_page_draw import (
    RetryProvenance,
    _edition,
    _inventory,
    _page,
    _provider_brief,
    _reference_files,
)

CAMERA = PanelCamera(shot="medium", angle="eye_level")


def _acting(entity_id="worth", facing="profile_left", expression="bored"):
    return CharacterActing(entity_id=entity_id, facing=facing, gaze="mop", expression=expression)


def _content(order, *, acting=(), entity_ids=("worth", "mop"), camera=CAMERA):
    return PageContent(
        id=f"content-{order}", order=order, beat_ids=["beat-1"], visual_intent="Worth mops.",
        entity_ids=list(entity_ids), camera=camera, acting=tuple(acting),
    )


def _pages(*contents):
    return [SimpleNamespace(page_number=1, content=contents)]


INVENTORY = ApprovedVisualReferenceInventory(references=[
    ApprovedVisualReference(id="worth:base", entity_id="worth", visual_anchor="1man", kind="character"),
    ApprovedVisualReference(id="mop:base", entity_id="mop", visual_anchor="mop", kind="prop"),
])


def _codes(failures):
    return [failure.code for failure in failures]


def test_every_panel_needs_a_camera_and_every_visible_character_needs_acting():
    failures = _staging_failures(INVENTORY, _pages(_content(1, camera=None)))

    assert _codes(failures) == ["missing_panel_camera", "missing_character_acting"]
    assert "worth" in failures[1].evidence[0]


def test_props_are_not_acted():
    failures = _staging_failures(INVENTORY, _pages(
        _content(1, acting=[_acting(), _acting("mop")]),
    ))

    assert _codes(failures) == ["acting_for_non_character"]


def test_unknown_kinds_do_not_require_acting():
    unknown = ApprovedVisualReferenceInventory(references=[
        ApprovedVisualReference(id="worth:base", entity_id="worth", visual_anchor="1man"),
    ])

    assert _staging_failures(unknown, _pages(_content(1, entity_ids=("worth",)))) == []


def test_four_identical_performances_in_a_row_are_sent_back():
    repeated = [_content(i, acting=[_acting(expression="Bored!")]) for i in range(1, 4)]
    fourth = _content(4, acting=[_acting(expression="bored")])
    varied = _content(5, acting=[_acting(facing="away_from_viewer")])

    failures = _staging_failures(INVENTORY, _pages(*repeated, fourth, varied))

    assert _codes(failures) == ["repeated_character_acting"]
    assert list(failures[0].artifact_ids) == ["content-1", "content-2", "content-3", "content-4"]


def test_three_identical_performances_are_allowed():
    contents = [_content(i, acting=[_acting()]) for i in range(1, 4)]

    assert _staging_failures(INVENTORY, _pages(*contents)) == []


def test_a_character_only_ever_in_three_quarter_view_is_sent_back():
    facings = ["three_quarter_left", "three_quarter_right"] * 3
    contents = [
        _content(i, acting=[_acting(facing=facing, expression=f"mood {i}")])
        for i, facing in enumerate(facings, 1)
    ]

    assert _codes(_staging_failures(INVENTORY, _pages(*contents))) == ["reference_angle_only"]


def test_acting_must_name_a_visible_entity_once():
    with pytest.raises(ValidationError, match="visible entities"):
        _content(1, acting=[_acting("lab_coat")])
    with pytest.raises(ValidationError, match="at most one"):
        _content(1, acting=[_acting(), _acting()])


def test_draw_prompt_carries_camera_and_acting_on_subject_handles(tmp_path):
    page = _page()
    content = page.content[0].model_copy(update={
        "camera": PanelCamera(shot="close_up", angle="low_angle"),
        "acting": (CharacterActing(
            entity_id="ward", facing="profile_right", gaze="idol",
            expression="jaw slack, eyes wide", gesture="",
        ),),
    })
    page = page.model_copy(update={"content": (content,)})
    request = compile_page_generation_request(
        page, _edition(), _inventory(), _reference_files(tmp_path),
        retry=RetryProvenance(attempt=1),
    ).request
    panel = _provider_brief(request.prompt)["canonical_comic_page"]["content"][0]

    assert panel["camera"] == "close up shot, low angle"
    ward, idol = panel["visible_subjects"]
    assert ward["acting"]["facing"] == "profile right (reader's screen direction)"
    assert ward["acting"]["gaze"] == idol["subject"]
    assert ward["acting"]["expression"] == "jaw slack, eyes wide"
    assert "gesture" not in ward["acting"]
    assert "acting" not in idol
    assert '"idol"' not in request.prompt


def _character_prompt(*, state_id=None):
    return GenerationPromptInput(subjects=(PromptSubject(
        character_id="worth", name="Worth", identity="1man, grey coveralls",
        baseline_affect="gruff and unflappable", appearance_state_id=state_id,
    ),))


def test_canonical_sheet_is_a_neutral_turnaround_without_baked_mood():
    lines = generate_system_constraints(_character_prompt(), asset_kind="character_ref")
    text = "\n".join(lines)

    assert "exactly five depictions of that same character" in lines
    assert "full-body back view" in text
    assert "relaxed neutral expression" in text
    assert "gruff" not in text


def test_state_sheet_keeps_an_authored_state_affect():
    text = "\n".join(generate_system_constraints(
        _character_prompt(state_id="feverish"), asset_kind="character_ref",
    ))

    assert "state affect for Worth: gruff and unflappable" in text


def test_turnaround_sheet_crops_to_square_portrait_and_body_views(tmp_path):
    sheet = tmp_path / "sheet.png"
    Image.new("RGB", (1536, 1024)).save(sheet)

    _crop_sheet_to_poses(sheet)

    with Image.open(tmp_path / "portrait.png") as portrait:
        assert portrait.size == (512, 512)
    with Image.open(tmp_path / "full_body.png") as body:
        assert body.size == (1024, 1024)


def test_state_sheet_shows_the_changed_look_not_the_situation():
    lines = generate_system_constraints(
        _character_prompt(state_id="impaled"), asset_kind="character_ref",
    )
    text = "\n".join(lines)

    assert "exactly three depictions of that same character" in lines
    assert "neutral design stance" in text
    assert "objects that pierce, pin, bind or are held" in text
    assert "back view" not in text


def test_appearance_lock_fixes_the_look_without_copying_the_reference_image():
    prompt = GenerationPromptInput(subjects=(PromptSubject(
        character_id="worth", name="Worth", identity="1man", appearance_state_id="bloodied",
        appearance_locked=True,
    ),))
    text = "\n".join(generate_system_constraints(prompt, asset_kind="character_ref"))

    assert "fixed altered appearance" in text
    assert "as the reference image" not in text


def test_damage_only_character_states_reuse_the_canonical_reference():
    from novel_to_comic.models.appearance import AppearanceState
    from novel_to_comic.stages.s1_extract import _text_only_damage_states

    def state(id, facets, replaces=False):
        return AppearanceState(
            id=id, label=id, visual_anchor="1man, blood", visually_significant=True,
            changed_facets=facets, replaces_identity=replaces,
        )

    character = SimpleNamespace(appearance_states=[
        state("bloodied", ("damage",)),
        state("prison_garb", ("clothing", "damage")),
        state("transformed", ("damage",), replaces=True),
        state("feverish", ()),
    ])
    _text_only_damage_states(SimpleNamespace(characters=[character]))

    assert [s.visually_significant for s in character.appearance_states] == [False, True, True, True]

from types import SimpleNamespace

import pytest

from novel_to_comic.lettering import service
from novel_to_comic.lettering.direction import (
    direction_for, joined_to, mark_emphasis, voice_catalogue, voice_style,
)
from novel_to_comic.models.adaptation import LetteringItem
from novel_to_comic.models.page import PinnedGeometry


def _item(text, *, kind="dialogue", delivery="onscreen", speaker: str | None = "ada", units=("u1",), id="l1"):
    return LetteringItem(id=id, kind=kind, text=text, speaker="Ada" if speaker else None,
                         speaker_entity_id=speaker if delivery == "onscreen" else None,
                         delivery=delivery, source_unit_ids=units)


@pytest.mark.parametrize("prose,voice", [
    ('"Get down!" she shouted, diving for cover.', "shout"),
    ('She leaned close. "They can hear us," she whispered.', "whisper"),
    ('"Unit seven, respond," the voice crackled over the radio.', "radio"),
    ('"I can\'t... hold on," he gasped.', "weak"),
    ('"We should go," she said.', None),
    ('"Stay there," a voice came from the intercom.', "radio"),
    ('"Stay there," she said on her phone.', "radio"),
])
def test_voice_comes_from_the_source_speech_tag(prose, voice):
    line = prose.split('"')[1]
    assert direction_for(_item(line), {"u1": prose}).voice == voice


def test_a_neighbouring_line_does_not_lend_its_tag():
    prose = '"We should go," Ada said. "Not yet," Ben whispered.'
    assert direction_for(_item("We should go,"), {"u1": prose}).voice is None
    assert direction_for(_item("Not yet,", speaker="ben"), {"u1": prose}).voice == "whisper"


def test_copy_alone_sets_shouts_documents_and_place_tags():
    assert direction_for(_item("STOP RIGHT THERE!"), {}).voice == "shout"
    assert direction_for(_item("The letter read: come alone.", kind="caption", delivery="quoted_text", speaker=None), {}).voice == "journal"
    assert direction_for(_item("Arkham, 1928", kind="caption", delivery="narration", speaker=None), {}).voice == "location"
    assert direction_for(_item("Meanwhile, beneath the city", kind="caption", delivery="narration", speaker=None), {}).voice == "location"
    long = "She remembered the house in 1928 and every room of it, the light and the dust."
    assert direction_for(_item(long, kind="caption", delivery="narration", speaker=None), {}).voice is None


def test_capitals_in_mixed_copy_become_display_stress_only():
    item = _item("You did WHAT to the car? I said NEVER.")
    direction = direction_for(item, {})
    assert direction.emphasis == ("WHAT", "NEVER")
    assert mark_emphasis(item.text, direction.emphasis) == "You did *WHAT* to the car? I said *NEVER*."
    assert item.text == "You did WHAT to the car? I said NEVER."
    assert direction_for(_item("ALL OF IT, EVERYTHING."), {}).emphasis == ()


def test_voice_styles_match_the_shared_catalogue_and_keep_book_case():
    style = service.preset_style("classic")
    shout = voice_style(style.roles.speech, "speech", "shout")
    assert shout.shape == "burst" and shout.text_case == "upper" and shout.font == style.roles.speech.font
    impact = voice_style(style.roles.sfx, "sfx", "pop")
    assert impact.shadow == "none" and impact.warp == "arc"
    assert set(voice_catalogue()) == {"speech", "thought", "caption", "sfx"}


def test_one_speakers_consecutive_lines_join_and_share_one_tail():
    first, second = _item("Wait.", id="a"), _item("Listen to me.", id="b")
    other = _item("No.", speaker="ben", id="c")
    assert joined_to(first, second) and not joined_to(second, other) and not joined_to(None, first)
    box = PinnedGeometry(x=.15, y=.15, width=.35, height=.16)
    reservations = [SimpleNamespace(lettering_item_id=item.id, bounds=box, tail_target=None) for item in (first, second, other)]
    page = SimpleNamespace(content=[SimpleNamespace(order=1, lettering=[first, second, other])],
                           lettering_reservations=reservations, page_number=1, content_sha256="a" * 64)
    prose = {"u1": '"Wait." Ada grabbed his arm. "Listen to me," she whispered.'}
    state = service.seed_lettering(page, SimpleNamespace(width=1000, height=1250), service.preset_style(), sources=prose)
    lead, follower, reply = state.elements
    assert follower.link_to == "a" and follower.tail_target is None
    assert lead.tail_target is not None and reply.link_to is None and reply.tail_target is not None
    assert follower.style_override is not None and follower.style_override.shape == "whisper"
    assert lead.style_override is None


def test_only_art_only_samples_take_the_software_overlay(tmp_path):
    import json
    from novel_to_comic import artifacts
    from novel_to_comic.stages.s2_style import STYLE_PROOF_ART_CONSTRAINTS, sample_takes_software_lettering

    def sample(name, prompt):
        path = tmp_path / name
        path.write_bytes(b"png")
        if prompt is not None:
            artifacts.asset_meta_path(path).write_text(json.dumps({"prompt": prompt}))
        return path

    assert sample_takes_software_lettering(sample("art.png", "Old wording. " + STYLE_PROOF_ART_CONSTRAINTS))
    assert not sample_takes_software_lettering(sample("baked.png", "Draw the lettering directly into the image."))
    assert not sample_takes_software_lettering(sample("unknown.png", None))


def test_style_proofs_render_without_holding_the_project_lock(tmp_path, monkeypatch):
    import io
    from PIL import Image
    from novel_to_comic import artifact_lock
    from novel_to_comic.lettering import proof
    from novel_to_comic.target_artifacts import TargetArtifacts

    key = str(tmp_path.resolve())
    held = []
    monkeypatch.setattr(proof, "resolve_style_proof", lambda style, w, h: None)
    monkeypatch.setattr(proof, "render_lettered_page", lambda *args, **kwargs: (
        held.append(key in getattr(artifact_lock._local, "held", set())) or b"png"))
    buffer = io.BytesIO()
    Image.new("RGB", (40, 50), "#888").save(buffer, "PNG")
    data, identity = proof.render_style_proof(TargetArtifacts(tmp_path), service.preset_style(), buffer.getvalue())
    assert data == b"png" and held == [False]
    assert TargetArtifacts(tmp_path).lettering_proof_path(identity).read_bytes() == b"png"


def test_offscreen_alone_does_not_imply_radio_or_whisper():
    assert direction_for(_item("Stay there.", delivery="offscreen"), {}).voice is None

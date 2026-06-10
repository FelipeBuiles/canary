"""Tests for the LLM visual-brief pass and its fallbacks."""

import asyncio
from unittest.mock import AsyncMock, patch

from novel_to_comic.config import Config
from novel_to_comic.models.prompt import ImagePrompt, PromptSubject
from novel_to_comic.prompt_assembly import (
    ensure_visual_brief,
    normalize_prose_brief,
)
from novel_to_comic.prompting import (
    generate_distilled_prompt,
    render_generation_prompt,
    visual_brief_source_spec,
)
from novel_to_comic.usage import ApiResult


def _prompt(**overrides) -> ImagePrompt:
    base = dict(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="Carl pours bourbon.",
        subjects=[
            PromptSubject(
                character_id="char_carl",
                name="Carl",
                identity="40-year-old dentist, salt-and-pepper hair, wire-rimmed glasses",
                action="pours bourbon into a glass",
                expression="blank, dissociated",
                position="standing at the kitchen counter",
            )
        ],
        composition="medium vertical panel, low angle camera",
        setting="sparse modern kitchen with stainless appliances",
        lighting="warm tungsten, deep shadows",
        mood="quiet desperation",
        props=["bourbon bottle: unlabeled amber glass, half-empty"],
        visual_requirements=["visible hand tremor"],
        constraints="exactly 1 character; one body per listed character; no text",
        width=768,
        height=1344,
        steps=8,
    )
    base.update(overrides)
    return ImagePrompt(**base)


def test_visual_brief_source_spec_includes_all_fields():
    spec = visual_brief_source_spec(
        _prompt(has_narration_caption=True, preferred_caption_zone="top")
    )

    assert "Framing: medium vertical panel, low angle camera" in spec
    assert "Character — Carl: appearance: 40-year-old dentist" in spec
    assert "action: pours bourbon into a glass" in spec
    assert "Setting: sparse modern kitchen" in spec
    assert "Lighting: warm tungsten, deep shadows" in spec
    assert "Mood: quiet desperation" in spec
    assert "Props (with their fixed appearance): bourbon bottle" in spec
    assert "Must clearly show: visible hand tremor" in spec
    assert "Caption space: keep quiet, uncluttered negative space near the top" in spec
    assert "Hard constraints: exactly 1 character" in spec


def test_normalize_prose_brief_accepts_prose_and_strips_wrapping():
    raw = '```\nVisual brief: A low-angle medium shot of Carl, a 40-year-old dentist, pouring bourbon.\n```'
    assert normalize_prose_brief(raw) == (
        "A low-angle medium shot of Carl, a 40-year-old dentist, pouring bourbon."
    )


def test_normalize_prose_brief_rejects_lists_and_short_output():
    assert normalize_prose_brief("- bullet one\n- bullet two") is None
    assert normalize_prose_brief("Too short.") is None
    assert normalize_prose_brief("") is None


def test_ensure_visual_brief_disabled_returns_same_object():
    prompt = _prompt()
    config = Config(visual_brief_enabled=False)

    result = asyncio.run(ensure_visual_brief(config, prompt))

    assert result is prompt
    assert result.visual_brief is None


def test_ensure_visual_brief_populates_from_llm():
    prompt = _prompt()
    brief = (
        "A low-angle medium vertical shot of Carl, a 40-year-old dentist with "
        "salt-and-pepper hair and wire-rimmed glasses, standing at the kitchen "
        "counter pouring bourbon, his hand visibly trembling."
    )
    with patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(return_value=ApiResult(value=brief, usage=None)),
    ):
        result = asyncio.run(ensure_visual_brief(Config(), prompt))

    assert result is not prompt
    assert result.visual_brief == brief


def test_ensure_visual_brief_falls_back_on_llm_failure():
    prompt = _prompt()
    with patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(side_effect=RuntimeError("gateway down")),
    ):
        result = asyncio.run(ensure_visual_brief(Config(), prompt))

    assert result is prompt
    assert result.visual_brief is None


def test_ensure_visual_brief_keeps_existing_brief():
    prompt = _prompt(visual_brief="Existing brief that is long enough to be kept around.")
    with patch(
        "novel_to_comic.clients.text.generate_text",
        new=AsyncMock(side_effect=AssertionError("should not be called")),
    ):
        result = asyncio.run(ensure_visual_brief(Config(), prompt))

    assert result is prompt


def test_render_generation_prompt_prefers_visual_brief_over_distilled():
    prompt = _prompt(
        visual_brief="A prose brief of the panel that is comfortably long enough.",
        distilled_prompt="distilled body",
    )

    generation_prompt = render_generation_prompt(prompt, "Ink wash.")

    assert "Visual brief:\nA prose brief of the panel" in generation_prompt
    assert "distilled body" not in generation_prompt


def test_distilled_prompt_keeps_caption_space_and_lighting():
    prompt = _prompt(
        has_narration_caption=True,
        preferred_caption_zone="top_left",
        composition=(
            "medium vertical panel, low angle camera, leave quiet negative space "
            "near the top left for a narration caption added later"
        ),
        # Lighting whose tokens all overlap with setting/subject phrasing used
        # to be deleted wholesale by token dedup.
        setting="kitchen lit by warm tungsten light, deep shadows",
        lighting="warm tungsten, deep shadows",
    )

    distilled = generate_distilled_prompt(prompt)

    assert "narration caption added later" in distilled
    assert "warm tungsten" in distilled.split(".", 1)[1]  # lighting survives dedup

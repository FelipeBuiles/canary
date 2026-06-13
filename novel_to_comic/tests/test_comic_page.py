"""Tests for comic page models (models/comic_page.py)."""

import pytest
from pydantic import ValidationError

from novel_to_comic.models.comic_page import (
    Bubble,
    Sfx,
    PagePanel,
    ComicPage,
    CharacterVoice,
    BUBBLE_PRESETS,
    normalize_sfx_text,
)


class TestBubbleDefaults:
    def test_speech_type_default(self):
        b = Bubble(id="s1-p1-b1", text="Hello world")
        assert b.type == "speech"
        assert b.side == "left"
        assert b.tail_direction == "auto"

    def test_auto_position_by_default(self):
        b = Bubble(id="s1-p1-b1", text="Hmm")
        assert b.x is None
        assert b.y is None
        assert b.width is None

    def test_tail_target_none_by_default(self):
        b = Bubble(id="s1-p1-b1", text="Wow!")
        assert b.tail_x is None
        assert b.tail_y is None


class TestBubbleTypes:
    def test_speech_bubble(self):
        b = Bubble(id="s1-p1-b1", type="speech", text="Hello!")
        assert b.type == "speech"

    def test_thought_bubble(self):
        b = Bubble(id="s1-p1-b1", type="thought", text="I wonder...")
        assert b.type == "thought"

    def test_narration_bubble(self):
        b = Bubble(id="s1-p1-b1", type="narration", text="Meanwhile...")
        assert b.type == "narration"

    def test_invalid_type_rejected(self):
        with pytest.raises(ValidationError):
            Bubble(id="s1", type="scream", text="Yikes!")


class TestBubbleTypographyOverrides:
    def test_all_typography_fields_optional(self):
        b = Bubble(
            id="s1-p1-b1",
            text="Hello",
            font_family="Comic Sans",
            font_size=14,
            font_color="#ff0000",
            fill_color="#ffff00",
            border_color="#000000",
            border_width=3,
            border_radius=8,
        )
        assert b.font_family == "Comic Sans"
        assert b.font_size == 14


class TestSfx:
    def test_default_rotation(self):
        s = Sfx(text="POW!")
        assert s.rotation == -4.0

    def test_explicit_position(self):
        s = Sfx(text="BAM!", x=100.0, y=200.0, rotation=15.0)
        assert s.x == 100.0
        assert s.y == 200.0
        assert s.rotation == 15.0


class TestSfxValidation:
    def test_text_validator_strips_markup(self):
        s = Sfx(text="[SFX: BOOM]")
        assert s.text == "BOOM"

    def test_text_validator_rejects_empty(self):
        with pytest.raises(ValidationError):
            Sfx(text="[SFX: ]")

    def test_defaults(self):
        s = Sfx(text="POW")
        assert s.kind == "impact"
        assert s.intensity == 2
        assert s.anchor == "auto"


class TestPagePanelSfxMigration:
    def test_legacy_null_becomes_empty_list(self):
        panel = PagePanel(
            id="x", image_path="a.png", scene_id="s", panel_number=1, sfx=None
        )
        assert panel.sfx == []

    def test_legacy_single_dict_becomes_singleton_list(self):
        panel = PagePanel(
            id="x", image_path="a.png", scene_id="s", panel_number=1,
            sfx={"text": "BOOM"},
        )
        assert len(panel.sfx) == 1
        assert panel.sfx[0].text == "BOOM"

    def test_legacy_single_with_markup_gets_cleaned(self):
        panel = PagePanel(
            id="x", image_path="a.png", scene_id="s", panel_number=1,
            sfx={"text": "[SFX: CRACK]"},
        )
        assert panel.sfx[0].text == "CRACK"

    def test_list_of_sfx_passes_through(self):
        panel = PagePanel(
            id="x", image_path="a.png", scene_id="s", panel_number=1,
            sfx=[{"text": "BOOM"}, {"text": "AAH", "kind": "voice"}],
        )
        assert [s.text for s in panel.sfx] == ["BOOM", "AAH"]
        assert panel.sfx[1].kind == "voice"


class TestInferSfxKind:
    def test_impact_default(self):
        from novel_to_comic.models.comic_page import infer_sfx_kind
        assert infer_sfx_kind("BOOM") == "impact"
        assert infer_sfx_kind("CRACK") == "impact"

    def test_mechanical(self):
        from novel_to_comic.models.comic_page import infer_sfx_kind
        assert infer_sfx_kind("BEEP") == "mechanical"
        assert infer_sfx_kind("click click") == "mechanical"

    def test_voice(self):
        from novel_to_comic.models.comic_page import infer_sfx_kind
        assert infer_sfx_kind("AAH!") == "voice"
        assert infer_sfx_kind("gasp") == "voice"


class TestInferSfxIntensity:
    def test_loud_caps_with_emphasis(self):
        from novel_to_comic.models.comic_page import infer_sfx_intensity
        assert infer_sfx_intensity("BOOM!!!") == 3
        assert infer_sfx_intensity("KRAAAKOOM") == 3

    def test_medium_caps(self):
        from novel_to_comic.models.comic_page import infer_sfx_intensity
        assert infer_sfx_intensity("BOOM") == 2

    def test_quiet_lowercase(self):
        from novel_to_comic.models.comic_page import infer_sfx_intensity
        assert infer_sfx_intensity("rustle") == 1


class TestNormalizeSfxText:
    def test_passthrough_clean_onomatopoeia(self):
        assert normalize_sfx_text("BOOM") == "BOOM"
        assert normalize_sfx_text("KRA-KOOM!") == "KRA-KOOM!"

    def test_strips_bracket_markup(self):
        assert normalize_sfx_text("[SFX: BOOM]") == "BOOM"
        assert normalize_sfx_text("[SFX: TAT-DE-TA-TA-TA]") == "TAT-DE-TA-TA-TA"

    def test_strips_bare_prefix(self):
        assert normalize_sfx_text("SFX: WHOOSH") == "WHOOSH"
        assert normalize_sfx_text("sfx: crash") == "crash"

    def test_strips_only_brackets(self):
        assert normalize_sfx_text("[CRACK]") == "CRACK"

    def test_handles_whitespace(self):
        assert normalize_sfx_text("  [  SFX:  BAM  ]  ") == "BAM"

    def test_returns_none_for_empty(self):
        assert normalize_sfx_text("") is None
        assert normalize_sfx_text(None) is None
        assert normalize_sfx_text("   ") is None
        assert normalize_sfx_text("[SFX:]") is None
        assert normalize_sfx_text("[]") is None

    def test_preserves_inner_punctuation(self):
        assert normalize_sfx_text("[SFX: BANG!?]") == "BANG!?"


class TestPagePanel:
    def test_panels_default_empty(self):
        panel = PagePanel(
            id="scene_001-003",
            image_path="draw/scene_001/panel_003.png",
            scene_id="scene_001",
            panel_number=3,
        )
        assert panel.bubbles == []
        assert panel.sfx == []
        assert panel.grid_column is None

    def test_with_bubbles(self):
        panel = PagePanel(
            id="scene_001-001",
            image_path="draw/scene_001/panel_001.png",
            scene_id="scene_001",
            panel_number=1,
            bubbles=[
                Bubble(id="scene_001-1-b1", type="speech", text="Hi!"),
                Bubble(id="scene_001-1-b2", type="narration", text="Meanwhile..."),
            ],
        )
        assert len(panel.bubbles) == 2
        assert panel.bubbles[0].text == "Hi!"

    def test_grid_placement(self):
        panel = PagePanel(
            id="scene_001-001",
            image_path="draw/scene_001/panel_001.png",
            scene_id="scene_001",
            panel_number=1,
            grid_column="1 / 3",
            grid_row="2 / 4",
        )
        assert panel.grid_column == "1 / 3"
        assert panel.grid_row == "2 / 4"


class TestComicPageDefaults:
    def test_layout_defaults(self):
        page = ComicPage(page_number=1)
        assert page.layout == "4"
        assert page.layout_mode == "grid"


class TestComicPageWithPanels:
    def test_page_with_multiple_panels(self):
        page = ComicPage(
            page_number=1,
            panels=[
                PagePanel(
                    id="scene_001-001",
                    image_path="draw/scene_001/panel_001.png",
                    scene_id="scene_001",
                    panel_number=1,
                ),
                PagePanel(
                    id="scene_002-001",
                    image_path="draw/scene_002/panel_001.png",
                    scene_id="scene_002",
                    panel_number=1,
                ),
            ],
        )
        assert len(page.panels) == 2


class TestBubblePresets:
    def test_speech_preset(self):
        assert "speech" in BUBBLE_PRESETS
        assert BUBBLE_PRESETS["speech"]["border_radius"] == "10"

    def test_thought_preset(self):
        assert "thought" in BUBBLE_PRESETS
        assert BUBBLE_PRESETS["thought"]["border_radius"] == "22"

    def test_narration_preset(self):
        assert "narration" in BUBBLE_PRESETS
        assert BUBBLE_PRESETS["narration"]["fill_color"] == "#f0ebe0"

    def test_shout_preset(self):
        assert "shout" in BUBBLE_PRESETS
        assert BUBBLE_PRESETS["shout"]["fill_color"] == "#e8c840"

    def test_all_presets_have_required_keys(self):
        for name, preset in BUBBLE_PRESETS.items():
            assert "border_radius" in preset
            assert "border_width" in preset
            assert "border_color" in preset
            assert "fill_color" in preset


class TestCharacterVoice:
    def test_minimal(self):
        v = CharacterVoice(character_id="char_001", character_name="Alice")
        assert v.font_family is None
        assert v.font_size is None

    def test_full_override(self):
        v = CharacterVoice(
            character_id="char_001",
            character_name="Alice",
            font_family="Impact",
            font_size=18,
            font_color="#000000",
            fill_color="#ffffff",
            border_color="#000000",
            border_width=2,
            border_radius=4,
        )
        assert v.font_family == "Impact"
        assert v.font_size == 18

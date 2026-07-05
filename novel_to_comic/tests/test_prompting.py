"""Tests for image prompt composition."""

import sys
from pathlib import Path

workspace_root = str(Path(__file__).parent.parent.parent)
if workspace_root not in sys.path:
    sys.path.insert(0, workspace_root)

from novel_to_comic.config import Config  # noqa: E402
from novel_to_comic.models.layout_plan import PlannedPanel  # noqa: E402
from novel_to_comic.models.prompt import ImagePrompt, PromptSubject  # noqa: E402
from novel_to_comic.models.appearance import (  # noqa: E402
    AppearanceState,
    StateActivation,
    StoryPosition,
    Transition,
)
from novel_to_comic.models.story_bible import (  # noqa: E402
    Character,
    Location,
    Prop,
    Scene,
    StoryBible,
)
from novel_to_comic.prompting import (  # noqa: E402
    build_planned_panel_prompt_spec,
    dimensions_for_panel,
    generate_distilled_prompt,
    render_generation_prompt,
    visual_brief_source_spec,
)


def _story_bible() -> StoryBible:
    return StoryBible(
        title="The Flowers",
        author="Alice Walker",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name="Myop",
                visual_anchor=(
                    "1girl, child, black girl, dark skin, brown eyes, short hair, "
                    "afro textured hair, simple dress, barefoot"
                ),
                age_range="ten",
                gender="female",
                distinguishing_features=["dark brown skin"],
                default_outfit="A simple dress. She is barefoot.",
                relationships=[],
                first_appearance_scene="scene_002",
            )
        ],
        locations=[
            Location(
                id="loc_002",
                name="The gloomy cove",
                visual_anchor="outdoors, day, woods, forest, sweetsuds bush",
                mood="gloomy",
            )
        ],
        scenes=[
            Scene(
                id="scene_002",
                chapter=1,
                title="A New Path",
                location_id="loc_002",
                character_ids=["char_001"],
                summary="Myop gathers flowers in the woods.",
                scene_type="transition",
                narrative_beat="inciting_incident",
                source_start_quote="She had explored the woods",
            )
        ],
        narrative_arcs=[],
        props=[
            Prop(
                id="prop_001",
                name="Blue flowers",
                visual_anchor="small vivid blue flowers with velvety petals",
                first_appearance_scene="scene_002",
            )
        ],
    )


def _flowers_story_bible() -> StoryBible:
    return StoryBible(
        title="The Flowers",
        author="Alice Walker",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name="Myop",
                visual_anchor="1girl, child, black skin, short hair, simple dress, barefoot",
                age_range="10",
                gender="female",
                distinguishing_features=["dark brown skin"],
                default_outfit="A simple cotton dress. Barefoot.",
                relationships=[],
                first_appearance_scene="scene_002",
            )
        ],
        locations=[
            Location(
                id="loc_002",
                name="Spring bank",
                visual_anchor="stream, silver ferns, wild flowers, shallow water",
                mood="quiet",
            )
        ],
        scenes=[
            Scene(
                id="scene_002",
                chapter=1,
                title="Spring bank",
                location_id="loc_002",
                character_ids=["char_001"],
                summary="Myop follows the fence to the stream.",
                scene_type="transition",
                narrative_beat="wandering",
                source_start_quote="She followed the fence",
            )
        ],
        narrative_arcs=[],
        props=[
            Prop(
                id="prop_001",
                name="Knobby Stick",
                visual_anchor="A short, sturdy wooden branch with knobby protrusions.",
                first_appearance_scene="scene_001",
            ),
            Prop(
                id="prop_002",
                name="Bundle of Flowers",
                visual_anchor=(
                    "A large, messy armful of wild forest flora. It is NOT a formal bouquet. "
                    "The bundle is carried awkwardly in the crook of the arm or held against the chest."
                ),
                first_appearance_scene="scene_003",
            ),
        ],
    )


def test_prompt_collapses_sequential_same_character_action_to_single_instant(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_002",
        scene_id="scene_002",
        panel_number=2,
        beat_ids=["scene_002:beat_003", "scene_002:beat_004"],
        shot_type="close-up",
        camera_angle="from behind, then low side angle",
        characters_present=["char_001"],
        character_actions={
            "char_001": "crouches to inspect flowers, then rises and buries her face in the sweetsuds buds"
        },
        character_positions={"char_001": "center"},
        background_description="Blue velvety flowers in the foreground.",
        camera_note=(
            "A tight view on her hands and upper body as she lifts the blue flowers, "
            "then leans into the fragrant bush with her bundle crowding her chin."
        ),
        lighting="soft warm filtered light",
        mood="curious delighted",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())

    assert "buries her face in the sweetsuds buds" in prompt.full_prompt
    assert "rises and buries" not in prompt.full_prompt
    assert "low side angle camera" in prompt.full_prompt
    assert "from behind, then low side angle" not in prompt.full_prompt
    assert "crouches to inspect flowers" not in prompt.full_prompt
    assert "leans into the fragrant bush with her bundle crowding her chin" in prompt.full_prompt
    assert "lifts the blue flowers" not in prompt.full_prompt
    assert "single frozen instant, not a sequence or split-screen" in prompt.constraints


def _stumps_story_bible() -> StoryBible:
    """A protagonist with a visually-significant 'stumps' state active in scene_002."""
    bible = _story_bible()
    char = bible.characters[0]
    char.appearance_states = [
        AppearanceState(
            id="stumps",
            label="Maimed",
            visual_anchor="1girl, child, dark skin, simple dress, barefoot, arm stumps, bandaged ends",
            visually_significant=True,
            continuity_guard=(
                "She has no hands — both arms end in bandaged stumps; never depict her "
                "holding or gripping; she acts with her mouth or against her stumps"
            ),
        )
    ]
    char.appearance_timeline = [
        StateActivation(state_id="stumps", at=StoryPosition(scene_id="scene_002")),
    ]
    return bible


def test_significant_state_locks_appearance_in_constraints_and_brief(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_009",
        scene_id="scene_002",
        panel_number=9,
        beat_ids=["scene_002:beat_009"],
        shot_type="medium",
        camera_angle="eye-level",
        characters_present=["char_001"],
        character_actions={"char_001": "eats a pear"},
        character_positions={"char_001": "center"},
        lighting="moonlight",
        mood="tender",
    )
    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _stumps_story_bible())

    subject = prompt.subjects[0]
    assert subject.appearance_locked is True
    assert subject.appearance_guard and "no hands" in subject.appearance_guard

    # Hard constraint forbids reverting to the default look (carries the guard).
    assert "fixed altered appearance" in prompt.constraints
    assert "do not restore" in prompt.constraints
    assert "never depict her holding or gripping" in prompt.constraints

    # The brief pass elevates the locked subject + stages around it.
    spec = visual_brief_source_spec(prompt)
    assert "APPEARANCE LOCKED" in spec
    assert "Continuity rule: She has no hands" in spec
    assert "never write" in spec  # staging instruction present


def test_base_look_character_is_not_locked(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_001",
        scene_id="scene_002",
        panel_number=1,
        beat_ids=["scene_002:beat_001"],
        shot_type="medium",
        camera_angle="eye-level",
        characters_present=["char_001"],
        character_actions={"char_001": "gathers flowers"},
        character_positions={"char_001": "center"},
        lighting="soft",
        mood="curious",
    )
    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())
    assert prompt.subjects[0].appearance_locked is False
    assert "fixed altered appearance" not in (prompt.constraints or "")
    assert "APPEARANCE LOCKED" not in visual_brief_source_spec(prompt)


def test_prompt_does_not_split_non_sequential_then_phrase(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_001",
        scene_id="scene_002",
        panel_number=1,
        shot_type="wide",
        camera_angle="low angle",
        characters_present=["char_001"],
        character_actions={
            "char_001": "bounces between the trees, veering left then right along no particular path"
        },
        character_positions={"char_001": "center"},
        background_description="Dense woods behind a farmhouse.",
        camera_note="A wide establishing view with the girl darting through the foreground.",
        lighting="warm dappled morning light",
        mood="playful safe",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())

    assert "veering left then right along no particular path" in prompt.full_prompt


def test_generation_prompt_uses_structured_brief_and_noise_guardrails(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_001",
        scene_id="scene_002",
        panel_number=1,
        shot_type="wide",
        camera_angle="low angle",
        characters_present=["char_001"],
        character_actions={"char_001": "walks through the woods"},
        character_positions={"char_001": "center"},
        background_description="Dense woods behind a farmhouse.",
        lighting="warm morning light",
        mood="playful safe",
    )
    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())

    generation_prompt = render_generation_prompt(
        prompt,
        "Oil painting with broad expressive brushwork.",
    )

    assert "Style:\nOil painting with broad expressive brushwork." in generation_prompt
    assert "Visual brief:\nwide vertical panel" in generation_prompt
    # Identity binds immediately after the name, before the action.
    assert "Myop, " in generation_prompt
    assert "walks through the woods" in generation_prompt
    assert "Characters:\n" not in generation_prompt
    assert "Composition:\n" not in generation_prompt
    assert "Constraints:\n- exactly 1 character" in generation_prompt
    # Per-panel anti-duplication guards are emitted verbatim (no keyword filter).
    assert "- one body per listed character" in generation_prompt
    assert "- single frozen instant" in generation_prompt
    # Surface discipline rides the Style section (style mentions brushwork);
    # the old negative artifact-vocabulary paragraph is gone.
    assert "Render clean, coherent surfaces with readable forms" in generation_prompt
    assert "Avoid stochastic grain" not in generation_prompt
    # No refs supplied → no reference-image constraint line.
    assert "reference images" not in generation_prompt.lower()
    assert "One unified scene filling the entire canvas" in generation_prompt


def test_generation_prompt_prefers_distilled_prompt():
    prompt = ImagePrompt(
        scene_id="scene_004",
        panel_number=4,
        full_prompt="Composition: medium shot. Setting: library.",
        distilled_prompt="Medium shot inside the library, Ada crossing the lamplight.",
        composition="medium shot",
        setting="library",
        constraints="exactly 1 character; no text",
        width=768,
        height=1024,
        steps=28,
    )

    generation_prompt = render_generation_prompt(prompt, "Ink and watercolor.")

    assert "Visual brief:\nMedium shot inside the library" in generation_prompt
    assert "Composition:\nmedium shot" not in generation_prompt
    assert "Constraints:\n- exactly 1 character" in generation_prompt


def test_generate_distilled_prompt_binds_identity_to_name():
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="Ada, short black bob haircut, blue jacket. Composition: medium panel.",
        subjects=[
            PromptSubject(
                character_id="ada",
                name="Ada",
                identity="short black bob haircut, blue jacket",
                action="standing",
                expression="neutral",
                position="center frame",
            )
        ],
        composition="medium panel",
        setting="library",
        constraints="exactly 1 character; no text",
        width=768,
        height=1344,
        steps=8,
    )

    distilled = generate_distilled_prompt(prompt)

    # Appearance immediately follows the name so attributes bind to the right
    # character; action/expression/position come after.
    assert distilled.startswith("medium panel of Ada, short black bob haircut, blue jacket, standing")
    assert "library" in distilled


def test_generate_distilled_prompt_removes_caption_space_fragments():
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        composition=(
            "wide vertical panel, environment dominant, high angle camera, "
            "leave quiet negative space near the top for a narration caption added later"
        ),
        key_objects=["streetlamp", "apartment_building"],
        setting=(
            "night, outdoors, freezing, snow, ice, tree, sidewalk, streetlamp, "
            "7-story apartment building, winter storm, dark, cold lighting, urban, "
            "city street, residential, overcast; snowdrifts along the curb, wind-driven flakes"
        ),
        lighting="cold blue night with a single sodium streetlamp and faint warm window glow",
        mood="ominous",
        visual_requirements=[
            "Dark city street buried in snow at 2:23 AM",
            "Seven-story apartment building looming behind a bare tree",
        ],
        constraints="exactly 0 characters; no text",
        width=768,
        height=1344,
        steps=8,
    )

    distilled = generate_distilled_prompt(prompt)

    assert "leave quiet negative space" not in distilled
    assert "near the." not in distilled
    assert "apartment building" in distilled
    assert "apartment_building" not in distilled
    assert distilled.startswith(
        "wide vertical panel, environment dominant, high angle camera of streetlamp and apartment building."
    )


def test_generate_distilled_prompt_does_not_leave_dangling_shortened_clause():
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        composition=(
            "wide vertical panel, environment dominant, high angle camera, "
            "foreground framed with"
        ),
        setting="frozen residential street",
        constraints="exactly 0 characters; no text",
        width=768,
        height=1344,
        steps=8,
    )

    distilled = generate_distilled_prompt(prompt)

    assert "with." not in distilled
    assert distilled.startswith("wide vertical panel, environment dominant, high angle camera.")


def test_gpt_image_2_generation_prompt_adds_material_discipline():
    prompt = ImagePrompt(
        scene_id="scene_004",
        panel_number=4,
        composition="close-up detail shot, environment or object filling the panel",
        setting="leaf mold, dirt, rotted denim, corroded buckles, cracked bone",
        lighting="low diffuse woodland light",
        mood="macabre",
        visual_requirements=[
            "large white teeth are cracked",
            "last threads of faded blue denim cling to the skeleton",
            "two dull green corroded overall buckles rest on the ribcage",
        ],
        constraints="exactly 0 characters; no text",
        width=768,
        height=1024,
        steps=28,
    )

    gpt_prompt = render_generation_prompt(
        prompt,
        "Matte gouache, broad opaque shapes.",
        "openai/gpt-image-2",
    )
    gemini_prompt = render_generation_prompt(
        prompt,
        "Matte gouache, broad opaque shapes.",
        "image-balanced",
    )

    assert gemini_prompt.startswith("Create one finished scene image using the selected style.")
    assert "Create one finished comic panel image" not in gemini_prompt
    assert "Rendering discipline:\nGPT-image-2 material discipline" in gpt_prompt
    assert "do not cover surfaces with many similar flecks" in gpt_prompt
    assert "Keep quiet planes on bone, fabric, metal" in gpt_prompt
    assert "Rendering discipline:" not in gemini_prompt


def test_prompt_carries_key_objects_and_must_show_requirements(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_003",
        scene_id="scene_002",
        panel_number=3,
        beat_ids=["scene_002:beat_004"],
        shot_type="close-up",
        camera_angle="high angle",
        characters_present=["char_001"],
        character_actions={"char_001": "pinches the blue flowers between careful fingers"},
        character_expressions={"char_001": "mouth still, eyes fixed on the petals"},
        character_positions={"char_001": "center foreground"},
        key_objects=["Blue flowers"],
        visual_requirements=[
            "show the blue flowers pressed between her fingers",
            "show her mouth still and eyes fixed on the petals",
        ],
        background_description="forest floor falls out of focus behind her hands",
        lighting="thin sunlight through leaves",
        mood="hushed",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _story_bible())
    generation_prompt = render_generation_prompt(prompt, "Ink wash, quiet naturalism.")

    assert "Key objects: Blue flowers" in prompt.full_prompt
    assert "Must show: show the blue flowers pressed between her fingers" in prompt.full_prompt
    assert "Blue flowers: small vivid blue flowers with velvety petals" in prompt.full_prompt
    assert "Visual brief:\nclose-up portrait" in generation_prompt
    assert "Blue flowers" in generation_prompt
    assert "show the blue flowers pressed between her fingers" in generation_prompt
    assert "Key objects:\n" not in generation_prompt
    assert "Key props:\n" not in generation_prompt


def test_rect_master_prompt_ignores_page_slot_aspect_for_image_shape(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_002",
        scene_id="scene_002",
        panel_number=2,
        shot_type="medium",
        shape_intent="rect",
        generation_mode="master",
        aspect_preference=0.3333333333333333,
        camera_angle="slightly elevated side view",
        characters_present=["char_001"],
        character_actions={"char_001": "walks beside the fence toward the stream"},
        character_positions={"char_001": "center"},
        background_description="Silver ferns and wild flowers crowd the water's edge.",
        lighting="bright natural daylight",
        mood="serene",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _flowers_story_bible())

    assert dimensions_for_panel(panel) == (768, 1344)
    assert prompt.width == 768
    assert prompt.height == 1344
    assert "narrow vertical column" not in prompt.composition


def test_generation_aspect_overrides_closeup_vertical_prompt(tmp_path):
    panel = PlannedPanel(
        panel_id="scene_002:panel_002",
        scene_id="scene_002",
        panel_number=2,
        shot_type="close-up",
        shape_intent="rect",
        generation_mode="master",
        generation_aspect_ratio=1.5,
        generation_width=1536,
        generation_height=1024,
        generation_shape="landscape",
        generation_aspect_source="page_geometry",
        camera_angle="eye-level",
        characters_present=["char_001"],
        character_actions={"char_001": "studies the other figure carefully"},
        character_positions={"char_001": "left"},
        background_description="White void.",
        lighting="soft diffuse light",
        mood="intense",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _flowers_story_bible())

    assert dimensions_for_panel(panel) == (1536, 1024)
    assert prompt.width == 1536
    assert prompt.height == 1024
    assert prompt.generation_aspect_ratio == 1.5
    assert prompt.generation_shape == "landscape"
    assert "vertical panel" not in prompt.composition
    assert "wide horizontal frame" in prompt.composition


def test_prompt_does_not_promote_ambient_flowers_to_carried_bundle_prop(tmp_path):
    prop_001_ref = tmp_path / "refs" / "props" / "prop_001" / "ref.png"
    prop_002_ref = tmp_path / "refs" / "props" / "prop_002" / "ref.png"
    prop_001_ref.parent.mkdir(parents=True)
    prop_002_ref.parent.mkdir(parents=True)
    prop_001_ref.write_bytes(b"stick")
    prop_002_ref.write_bytes(b"flowers")
    panel = PlannedPanel(
        panel_id="scene_002:panel_002",
        scene_id="scene_002",
        panel_number=2,
        shot_type="medium",
        characters_present=["char_001"],
        character_actions={"char_001": "walks beside the fence gripping her knobby stick"},
        character_positions={"char_001": "center"},
        key_objects=["prop_001", "prop_002", "Knobby Stick", "Bundle of Flowers"],
        visual_requirements=[
            "Silver ferns and wild flowers crowd the water's edge.",
            "Fence meeting the spring-fed stream.",
        ],
        background_description="Stream appears at the fence line; vegetation thickens.",
        lighting="bright natural daylight",
        mood="serene",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _flowers_story_bible())
    generation_prompt = render_generation_prompt(prompt, "Seventeenth-century oil painting.")

    assert "Knobby Stick" in prompt.key_objects
    assert "prop_002" not in prompt.key_objects
    assert "Bundle of Flowers" not in prompt.key_objects
    assert "refs/props/prop_001/ref.png" in prompt.reference_image_paths
    assert "refs/props/prop_002/ref.png" not in prompt.reference_image_paths
    assert "Knobby Stick" in generation_prompt
    assert "Key props:\n" not in generation_prompt
    assert "Bundle of Flowers:" not in generation_prompt


def test_interior_panel_drops_outdoor_tokens_from_location_anchor(tmp_path):
    """A bedroom-flashback panel must not inherit 'bike rack, moped, snow' from
    the scene's outdoor location anchor."""
    story_bible = StoryBible(
        title="DCC",
        author="Matt Dinniman",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name="Carl",
                visual_anchor="1man, adult male, short brown hair, leather jacket, boxers",
                age_range="late 20s",
                gender="male",
                distinguishing_features=["muscular build"],
                default_outfit="boxers, leather jacket, pink crocs",
                relationships=[],
                first_appearance_scene="scene_001",
            )
        ],
        locations=[
            Location(
                id="loc_001",
                name="Seattle Street",
                visual_anchor=(
                    "night, outdoors, snow, winter, cold, ruins, rubble, dark, "
                    "overcast, empty space, dirt, bicycle rack, moped, street lamp, "
                    "stop sign, debris"
                ),
                mood="apocalyptic",
            )
        ],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="The Transformation",
                location_id="loc_001",
                character_ids=["char_001"],
                summary="Carl outside in the cold.",
                scene_type="transition",
                narrative_beat="inciting_incident",
                source_start_quote="The transformation occurred",
            )
        ],
        narrative_arcs=[],
        props=[],
    )

    interior_panel = PlannedPanel(
        panel_id="scene_001:panel_003",
        scene_id="scene_001",
        panel_number=3,
        shot_type="close-up",
        camera_angle="over-shoulder",
        characters_present=["char_001"],
        character_actions={"char_001": "sits on the bed smoking"},
        character_positions={"char_001": "left"},
        background_description=(
            "rumpled bed, bedside lamp, winter darkness pressing in through the cracked window"
        ),
        lighting="warm bedside lamp",
        mood="tense",
    )

    prompt = build_planned_panel_prompt_spec(
        Config(), tmp_path, interior_panel, story_bible
    )

    # Outdoor-only concrete objects must not appear in the indoor panel.
    setting_lower = (prompt.setting or "").lower()
    assert "bicycle rack" not in setting_lower
    assert "moped" not in setting_lower
    assert "rubble" not in setting_lower
    assert "debris" not in setting_lower
    assert "stop sign" not in setting_lower
    # Background description still carries the actual interior cues.
    assert "rumpled bed" in setting_lower
    assert "bedside lamp" in setting_lower
    # Atmospheric tokens (night, winter, cold, dark, overcast) are retained.
    assert "night" in setting_lower
    assert "cold" in setting_lower


def test_exterior_panel_keeps_outdoor_location_anchor(tmp_path):
    story_bible = StoryBible(
        title="DCC",
        author="Matt Dinniman",
        total_scenes=1,
        characters=[],
        locations=[
            Location(
                id="loc_001",
                name="Seattle Street",
                visual_anchor=(
                    "night, outdoors, snow, winter, cold, dark, overcast, "
                    "bicycle rack, moped, street lamp"
                ),
                mood="apocalyptic",
            )
        ],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="Aftermath",
                location_id="loc_001",
                character_ids=[],
                summary="Empty street.",
                scene_type="transition",
                narrative_beat="rising_action",
                source_start_quote="Everything was gone",
            )
        ],
        narrative_arcs=[],
        props=[],
    )
    outdoor_panel = PlannedPanel(
        panel_id="scene_001:panel_006",
        scene_id="scene_001",
        panel_number=6,
        shot_type="wide",
        camera_angle="eye-level",
        characters_present=[],
        character_actions={},
        background_description=(
            "entire city block flattened, rubble where the apartment stood, distant fire on the horizon"
        ),
        lighting="cold blue night",
        mood="catastrophic",
    )
    prompt = build_planned_panel_prompt_spec(
        Config(), tmp_path, outdoor_panel, story_bible
    )
    # When background is clearly exterior, the outdoor anchor stays intact.
    setting_lower = (prompt.setting or "").lower()
    assert "bicycle rack" in setting_lower
    assert "moped" in setting_lower


def test_distilled_prompt_does_not_repeat_subject_tokens_in_setting():
    """Tokens already named in the subject clause should not be re-listed in
    the setting clause — a streetlamp should not appear four times in one
    distilled prompt."""
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        composition="wide vertical panel, environment dominant, eye-level camera",
        key_objects=["streetlamp", "snow"],
        setting=(
            "night, outdoors, snow, winter, cold, ruins, rubble, dark, overcast, "
            "empty space, dirt, bicycle rack, moped, street lamp, stop sign, debris; "
            "ruined city block, snow dusting the street, distant apartment facades still standing"
        ),
        lighting="cold blue night with one sodium streetlamp",
        mood="ominous",
        visual_requirements=[
            "Dark Seattle street at 2:23 AM with thin snow and frost on the pavement.",
            "A single streetlamp burning in an otherwise quiet, ruined block.",
        ],
        constraints="exactly 0 characters; no text",
        width=768,
        height=1344,
        steps=8,
    )

    distilled = generate_distilled_prompt(prompt)

    # streetlamp appeared 4x and snow 4x in the old format. Phrase-level dedup
    # cuts both substantially. "streetlamp" survives in the subject + one
    # natural-language phrase (lighting or must-show); "snow" is stripped from
    # the setting clause entirely.
    assert distilled.lower().count("streetlamp") <= 3
    assert distilled.lower().count(" snow") <= 2
    # The standalone "Key visible objects:" sentence is gone.
    assert "Key visible objects" not in distilled
    # Setting clause no longer redundantly lists "snow" (already in subject).
    setting_segment = distilled.split(".")[1] if "." in distilled else ""
    assert " snow," not in setting_segment.lower()


def test_distilled_prompt_surfaces_continuity_note():
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=2,
        subjects=[
            PromptSubject(
                character_id="char_001",
                name="Carl",
                identity="leather jacket, boxers, pink crocs",
                action="bursts out the front door",
                position="center",
            )
        ],
        composition="medium panel",
        setting="snowy sidewalk in front of seven-story apartment",
        lighting="cold blue night",
        mood="urgent",
        transition_in="smooth_continuation",
        transition_out="smooth_continuation",
        continuity_note=(
            "CONTINUING FROM: Carl shoves feet into pink Crocs in entryway. "
            "TRANSITION TYPE: smooth_continuation."
        ),
        constraints="exactly 1 character; no text",
        width=768,
        height=1344,
        steps=8,
    )

    distilled = generate_distilled_prompt(prompt)

    assert "CONTINUING FROM" in distilled or "smooth continuation" in distilled.lower()


def test_location_state_resolves_anchor_by_panel_position(tmp_path):
    """The location's active state is resolved per panel from its
    appearance_timeline: panels before the transition use the base anchor,
    panels at/after it use the post-state anchor and carry its state id."""
    story_bible = StoryBible(
        title="DCC",
        author="Matt Dinniman",
        total_scenes=1,
        characters=[],
        locations=[
            Location(
                id="loc_001",
                name="Seattle Street",
                visual_anchor=(
                    "night, outdoors, snow, brick apartment facade, "
                    "streetlamp, parked cars, sidewalk"
                ),
                mood="apocalyptic",
                appearance_states=[
                    AppearanceState(
                        id="loc_001_post",
                        label="Post-collapse aftermath",
                        visual_anchor=(
                            "night, flattened dirt, rubble, distant fire, "
                            "bicycle rack, moped, stop sign"
                        ),
                        visually_significant=True,
                    ),
                ],
                appearance_timeline=[
                    StateActivation(
                        state_id="loc_001_post",
                        at=StoryPosition(scene_id="scene_001", beat=4),
                        transition=Transition(label="the block collapses"),
                    ),
                ],
            )
        ],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="The Transformation",
                location_id="loc_001",
                character_ids=[],
                summary="The street collapses mid-scene",
                scene_type="transition",
                narrative_beat="inciting_incident",
                source_start_quote="The transformation occurred",
            )
        ],
        narrative_arcs=[],
        props=[],
    )

    panel_pre = PlannedPanel(
        panel_id="scene_001:panel_001",
        scene_id="scene_001",
        panel_number=1,
        beat_ids=["scene_001:beat_001", "scene_001:beat_002"],
        shot_type="wide",
        camera_angle="eye-level",
        characters_present=[],
        background_description="dark Seattle street, snow on the pavement, parked cars",
        lighting="cold blue night",
        mood="ominous",
    )
    panel_post = PlannedPanel(
        panel_id="scene_001:panel_006",
        scene_id="scene_001",
        panel_number=6,
        beat_ids=["scene_001:beat_005", "scene_001:beat_006"],
        shot_type="wide",
        camera_angle="eye-level",
        characters_present=[],
        background_description="entire block flattened, rubble where the apartment stood",
        lighting="dark, distant fire glow",
        mood="catastrophic",
    )

    pre_prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel_pre, story_bible)
    post_prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel_post, story_bible)

    pre_setting = (pre_prompt.setting or "").lower()
    post_setting = (post_prompt.setting or "").lower()

    # Pre-collapse panel uses the base anchor, NOT the post tags.
    assert "brick apartment facade" in pre_setting or "streetlamp" in pre_setting
    assert "rubble" not in pre_setting
    assert "bicycle rack" not in pre_setting
    assert pre_prompt.location_state_id is None

    # Post-collapse panel uses the post state's anchor and carries its id.
    assert "rubble" in post_setting or "flattened dirt" in post_setting
    assert "bicycle rack" in post_setting
    assert post_prompt.location_state_id == "loc_001_post"


def test_distilled_prompt_keeps_props_with_visual_anchor():
    """Removing the redundant key-objects sentence should not also drop props
    — props carry their own visual_anchor identity that must reach the model."""
    prompt = ImagePrompt(
        scene_id="scene_002",
        panel_number=1,
        subjects=[
            PromptSubject(
                character_id="char_001",
                name="Myop",
                identity="1girl, child, barefoot",
                action="cradles wildflowers",
                position="center",
            )
        ],
        composition="medium panel",
        setting="forest floor",
        props=["Bundle of Flowers: messy armful of wild forest flora"],
        constraints="exactly 1 character; no text",
        width=768,
        height=1344,
        steps=8,
    )
    distilled = generate_distilled_prompt(prompt)
    assert "Bundle of Flowers" in distilled


def test_prompt_keeps_bundle_prop_when_character_carries_flowers(tmp_path):
    prop_002_ref = tmp_path / "refs" / "props" / "prop_002" / "ref.png"
    prop_002_ref.parent.mkdir(parents=True)
    prop_002_ref.write_bytes(b"flowers")
    panel = PlannedPanel(
        panel_id="scene_003:panel_003",
        scene_id="scene_002",
        panel_number=3,
        shot_type="medium",
        characters_present=["char_001"],
        character_actions={"char_001": "cradles an armful of wildflowers against her chest"},
        character_positions={"char_001": "center"},
        key_objects=["prop_002", "Bundle of Flowers"],
        visual_requirements=["A vivid armful of wildflowers pressed to her chest."],
        background_description="The forest recedes behind the blossoms.",
        lighting="filtered daylight",
        mood="wonder",
    )

    prompt = build_planned_panel_prompt_spec(Config(), tmp_path, panel, _flowers_story_bible())

    assert "Bundle of Flowers" in prompt.key_objects
    assert "Bundle of Flowers: A large, messy armful" in prompt.full_prompt
    assert "refs/props/prop_002/ref.png" in prompt.reference_image_paths


def test_reve_prompt_injection():
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="Composition: medium shot.",
        composition="medium shot",
        setting="library",
        constraints="exactly 1 character; no text",
        width=768,
        height=1344,
        steps=8,
    )
    from novel_to_comic.ai.providers.base import RefImage
    refs = [
        RefImage(path=Path("refs/char_alice/front.png"), role="subject", label="Alice"),
        RefImage(path=Path("refs/style.png"), role="style", label="selected style"),
    ]
    
    generation_prompt = render_generation_prompt(prompt, "Ink wash.", "image-reve", refs=refs)

    assert "Reference images:" in generation_prompt
    assert (
        "Use <img>0</img> as the identity reference for Alice — match face, hair, build, "
        "and wardrobe; do not copy its pose or background." in generation_prompt
    )
    assert "Use <img>1</img> as the style reference for selected style." in generation_prompt
    # Refs present → the reference-handling constraint line is emitted.
    assert "- Use reference images for identity, palette, and continuity only" in generation_prompt


def test_non_reve_models_do_not_get_img_tags():
    """Verify that non-Reve models (GPT-Image-2, Gemini) don't receive <img> tags."""
    prompt = ImagePrompt(
        scene_id="scene_001",
        panel_number=1,
        full_prompt="Composition: medium shot.",
        composition="medium shot",
        setting="library",
        constraints="exactly 1 character; no text",
        width=768,
        height=1344,
        steps=8,
    )
    from novel_to_comic.ai.providers.base import RefImage
    refs = [
        RefImage(path=Path("refs/char_alice/front.png"), role="subject", label="Alice"),
        RefImage(path=Path("refs/style.png"), role="style", label="selected style"),
    ]
    
    # Test GPT-Image-2
    gpt_prompt = render_generation_prompt(prompt, "Ink wash.", "openai/gpt-image-2", refs=refs)
    assert "<img>" not in gpt_prompt, "GPT-Image-2 should not receive <img> tags"
    assert "</img>" not in gpt_prompt, "GPT-Image-2 should not receive </img> tags"
    
    # Test Gemini (image-balanced)
    gemini_prompt = render_generation_prompt(prompt, "Ink wash.", "image-balanced", refs=refs)
    assert "<img>" not in gemini_prompt, "Gemini should not receive <img> tags"
    assert "</img>" not in gemini_prompt, "Gemini should not receive </img> tags"



def test_reve_cast_clean_text_prompt():
    from novel_to_comic.stages.s3_cast import _character_ref_clean_text_prompt
    from novel_to_comic.models.story_bible import Character
    from novel_to_comic.config import Config
    
    char = Character(
        id="char_thurston",
        name="Francis Wayland Thurston",
        visual_anchor="A tall man with spectacles and a brown coat.",
        age_range="30",
        gender="male",
        distinguishing_features=["spectacles"],
        default_outfit="brown coat",
        relationships=[],
        first_appearance_scene="scene_001",
    )
    
    config = Config(style_template="Dark charcoal sketch style.")
    prompt_str = _character_ref_clean_text_prompt(config, char, addendum="Make him look studious")
    
    assert "Dark charcoal sketch style" in prompt_str
    assert "CHARACTER REFERENCE SHEET - Francis Wayland Thurston, male." in prompt_str
    assert "A tall man with spectacles and a brown coat" in prompt_str
    assert "Default clothing: brown coat" in prompt_str
    assert "USER FIX NOTE: Make him look studious" in prompt_str
    assert "divided into a 2x2 grid of four equal panels" in prompt_str
    assert "STYLE AUTHORITY" not in prompt_str
    assert "CAST IDENTITY LOCK" not in prompt_str


def test_reve_aspect_ratio_mapping():
    from litellm_handlers.reve_provider import _map_aspect_ratio
    assert _map_aspect_ratio("1024x1024") == "1:1"
    assert _map_aspect_ratio("1536x1024") == "3:2"
    assert _map_aspect_ratio("1024x1536") == "2:3"
    assert _map_aspect_ratio("1920x1080") == "16:9"
    assert _map_aspect_ratio("1080x1920") == "9:16"


def test_reve_refs_one_crop_per_character_and_capping():
    from novel_to_comic.image_ref_strategy import RefStrategy
    from novel_to_comic.ai.providers.base import RefImage

    refs = [
        RefImage(path=Path("refs/char_alice/front.png"), role="subject", label="Alice"),
        RefImage(path=Path("refs/char_alice/gesture.png"), role="subject", label="Alice"),
        RefImage(path=Path("refs/char_bob/three_quarter.png"), role="subject", label="Bob"),
        RefImage(path=Path("style.png"), role="style", label="Style"),
        RefImage(path=Path("loc.png"), role="location_plate", label="Loc"),
        RefImage(path=Path("prop.png"), role="prop", label="Prop"),
        RefImage(path=Path("cont.png"), role="continuity", label="Cont"),
    ]

    selected = RefStrategy("image-reve").select_panel_refs(refs, "wide establishing panel, low angle camera")

    assert len(selected) == 4
    names = [ref.path.name for ref in selected]
    # One crop per character, identity first; wide framing prefers the
    # full-body gesture crop over the front portrait crop.
    assert names[0] == "gesture.png"
    assert names[1] == "three_quarter.png"
    # Remaining slots fill with prop/continuity in canonical upload order.
    assert names[2] == "prop.png"
    assert names[3] == "cont.png"


def test_reve_refs_close_up_prefers_front_crop():
    from novel_to_comic.image_ref_strategy import RefStrategy
    from novel_to_comic.ai.providers.base import RefImage

    refs = [
        RefImage(path=Path("refs/char_alice/gesture.png"), role="subject", label="Alice"),
        RefImage(path=Path("refs/char_alice/front.png"), role="subject", label="Alice"),
        RefImage(path=Path("style.png"), role="style", label="Style"),
    ]

    selected = RefStrategy("image-reve").select_panel_refs(refs, "close-up panel, eye-level camera")

    names = [ref.path.name for ref in selected]
    assert names == ["front.png", "style.png"]


def _style_sample_bible() -> StoryBible:
    return StoryBible(
        title="DCC",
        author="Matt Dinniman",
        total_scenes=1,
        characters=[
            Character(
                id="char_001",
                name="Carl",
                visual_anchor="1man, adult male, leather jacket",
                age_range="late 20s",
                gender="male",
                distinguishing_features=[],
                default_outfit="",
                relationships=[],
                first_appearance_scene="scene_001",
            )
        ],
        locations=[
            Location(
                id="loc_001",
                name="Seattle Street",
                visual_anchor="outdoors, snow, winter",
                mood="apocalyptic",
            )
        ],
        scenes=[
            Scene(
                id="scene_001",
                chapter=1,
                title="The Transformation",
                location_id="loc_001",
                character_ids=["char_001"],
                summary="Carl outside.",
                scene_type="transition",
                narrative_beat="inciting_incident",
                source_start_quote="The transformation occurred",
            )
        ],
        narrative_arcs=[],
        props=[],
    )


def test_build_style_sample_prompt_fallback_body():
    from novel_to_comic.prompting import build_style_sample_prompt
    config = Config(style_template="Clinical, desaturated visual language.")

    prompt = build_style_sample_prompt(config, _style_sample_bible())

    # House-style sections: style first, prose body, one-liner constraints.
    assert "project's art direction" in prompt
    assert "Style:\nClinical, desaturated visual language." in prompt
    assert "Visual brief:" in prompt
    # Deterministic fallback uses first character + first location anchors.
    assert "1man, adult male, leather jacket" in prompt
    assert "outdoors, snow, winter" in prompt
    assert "Constraints:" in prompt
    assert "One unified scene filling the entire canvas" in prompt
    assert "Portrait 4:5 frame" in prompt
    # Old shouty/negative phrasing is gone.
    assert "STYLE AUTHORITY" not in prompt
    assert "free of any text" not in prompt


def test_build_style_sample_prompt_uses_llm_brief_when_given():
    from novel_to_comic.prompting import build_style_sample_prompt
    config = Config(style_template="Clinical, desaturated visual language.")
    brief = (
        "Carl, a broad-shouldered man in his late twenties in a worn leather jacket, "
        "stands ankle-deep in fresh snow on a dark Seattle street."
    )

    prompt = build_style_sample_prompt(config, _style_sample_bible(), brief=brief)

    assert brief in prompt
    # The deterministic fallback body is not also emitted.
    assert "A three-quarter view of one figure" not in prompt


def test_build_style_sample_prompt_adds_surface_discipline_for_texture_styles():
    from novel_to_comic.prompting import build_style_sample_prompt
    bible = _style_sample_bible()

    textured = build_style_sample_prompt(
        Config(style_template="Oil painting, visible brushwork, rich colour."), bible
    )
    clean = build_style_sample_prompt(
        Config(style_template="Clinical, desaturated visual language."), bible
    )

    assert "broad intentional structure" in textured
    assert "broad intentional structure" not in clean


def test_silver_hands_never_leak_before_their_activation(tmp_path):
    """The Girl Without Hands regression: silver hands are a CHARACTER state
    that begins at scene_009. A scene_003 panel that merely mentions washing
    'hands' must resolve to the base look — no silver in identity or prompt."""
    girl = Character(
        id="char_001",
        name="The Miller's Daughter",
        visual_anchor="1woman, adult female, long blonde hair, blue eyes, pale skin, simple peasant dress",
        age_range="20s",
        gender="female",
        distinguishing_features=["long blonde hair"],
        default_outfit="A simple peasant dress with a white apron.",
        relationships=[],
        first_appearance_scene="scene_003",
        appearance_states=[
            AppearanceState(
                id="silver",
                label="Silver hands",
                visual_anchor="1woman, long blonde hair, pale skin, peasant dress, polished silver prosthetic hands",
                visually_significant=True,
            ),
        ],
        appearance_timeline=[
            StateActivation(
                state_id="silver",
                at=StoryPosition(scene_id="scene_009"),
                transition=Transition(label="silver hands forged", cause="the King has them made"),
            ),
        ],
    )
    scenes = [
        Scene(
            id=f"scene_{i:03d}", chapter=1, title="t", location_id="loc_001",
            character_ids=["char_001"], summary="s", scene_type="action",
            narrative_beat="rising_action", source_start_quote="q",
        )
        for i in range(1, 10)
    ]
    bible = StoryBible(
        title="The Girl Without Hands", author="Grimm", total_scenes=9,
        characters=[girl],
        locations=[Location(id="loc_001", name="Mill", visual_anchor="mill yard, water wheel", mood="calm")],
        scenes=scenes, narrative_arcs=[], props=[],
    )

    early = PlannedPanel(
        panel_id="scene_003:panel_001", scene_id="scene_003", panel_number=1,
        beat_ids=["scene_003:beat_001"],
        characters_present=["char_001"],
        character_actions={"char_001": "washing her hands in a basin, water dripping from her fingers"},
        background_description="mill yard at dawn", lighting="soft dawn", mood="peaceful",
    )
    late = PlannedPanel(
        panel_id="scene_009:panel_001", scene_id="scene_009", panel_number=1,
        beat_ids=["scene_009:beat_002"],
        characters_present=["char_001"],
        character_actions={"char_001": "stands in the throne room"},
        background_description="palace hall", lighting="warm", mood="regal",
    )

    early_prompt = build_planned_panel_prompt_spec(Config(), tmp_path, early, bible)
    late_prompt = build_planned_panel_prompt_spec(Config(), tmp_path, late, bible)

    # scene_003: base look; "silver" appears nowhere despite "hands" in the action.
    assert "silver" not in early_prompt.subjects[0].identity.lower()
    assert "silver" not in early_prompt.full_prompt.lower()
    # scene_009: the silver-hands state is active.
    assert "silver" in late_prompt.subjects[0].identity.lower()


def test_prop_is_gated_by_its_debut_scene(tmp_path):
    """A prop never attaches to a panel before its first_appearance_scene, even
    when that panel names the prop verbatim."""
    bible = StoryBible(
        title="t", author="a", total_scenes=2,
        characters=[],
        locations=[Location(id="loc_001", name="L", visual_anchor="a room", mood="calm")],
        scenes=[
            Scene(
                id=f"scene_{i:03d}", chapter=1, title="t", location_id="loc_001",
                character_ids=[], summary="s", scene_type="action",
                narrative_beat="rising_action", source_start_quote="q",
            )
            for i in range(1, 3)
        ],
        narrative_arcs=[],
        props=[
            Prop(
                id="prop_001",
                name="The Forged Letters",
                visual_anchor="parchment letters sealed with red wax",
                first_appearance_scene="scene_002",
            )
        ],
    )
    before = PlannedPanel(
        panel_id="scene_001:panel_001", scene_id="scene_001", panel_number=1,
        beat_ids=["scene_001:beat_001"],
        visual_requirements=["the forged letters lie on the table"],
        background_description="a room", lighting="x", mood="y",
    )
    after = PlannedPanel(
        panel_id="scene_002:panel_001", scene_id="scene_002", panel_number=1,
        beat_ids=["scene_002:beat_001"],
        visual_requirements=["the forged letters lie on the table"],
        background_description="a room", lighting="x", mood="y",
    )

    before_prompt = build_planned_panel_prompt_spec(Config(), tmp_path, before, bible)
    after_prompt = build_planned_panel_prompt_spec(Config(), tmp_path, after, bible)

    assert all("Forged Letters" not in p for p in before_prompt.props)
    assert any("Forged Letters" in p for p in after_prompt.props)




